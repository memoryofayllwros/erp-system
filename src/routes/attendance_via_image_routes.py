# attendance_via_image_routes.py
import asyncio
import logging
import os
import uuid
from datetime import timedelta, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional
from src.utils.datetime_standarization_helpers import get_this_moment
from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


from infrastructure.redis_connection.redis_manager import redis_manager

base_url = os.getenv("BASE_URL")

logger = logging.getLogger(__name__)

router = APIRouter()

current_dir = Path(__file__).parent
templates_dir = current_dir.parent.parent / "assets" / "attendance_html"

templates = Jinja2Templates(directory=str(templates_dir))

# Thread-safe in-memory DB with better token management
# In-memory fallback token store (single-process only)
CHECKIN_TOKENS: Dict[str, Dict[str, Any]] = {}
CHECKIN_LOGS = []
# Add a lock for thread-safe operations
TOKENS_LOCK = Lock()

# Token expiration settings
TOKEN_EXPIRY_MINUTES = 15
CLEANUP_INTERVAL_SECONDS = 300  # Clean up expired tokens every 5 minutes


async def cleanup_expired_tokens():
    """Background task to clean up expired tokens"""
    while True:
        try:
            current_time = get_this_moment()
            with TOKENS_LOCK:
                expired_tokens = [
                    token
                    for token, data in CHECKIN_TOKENS.items()
                    if current_time > data["expires_at"]
                ]

                for token in expired_tokens:
                    del CHECKIN_TOKENS[token]
                    logging.info(f"Cleaned up expired token: {token[:8]}...")

                if expired_tokens:
                    logging.info(f"Cleaned up {len(expired_tokens)} expired tokens")

        except Exception as e:
            logging.error(f"Error during token cleanup: {e}")

        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


# Start cleanup task when the module loads
cleanup_task = None


def start_cleanup_task():
    global cleanup_task
    if cleanup_task is None or cleanup_task.done():
        cleanup_task = asyncio.create_task(cleanup_expired_tokens())


def invalidate_existing_tokens_for_user(user_waba: str):
    """Invalidate any existing tokens for this WhatsApp number - thread safe"""
    with TOKENS_LOCK:
        tokens_to_invalidate = []
        for token, data in CHECKIN_TOKENS.items():
            if data["user_waba"] == user_waba and not data["used"]:
                tokens_to_invalidate.append(token)

        for token in tokens_to_invalidate:
            CHECKIN_TOKENS[token]["used"] = True
            CHECKIN_TOKENS[token]["invalidated_at"] = get_this_moment()
            logging.info(f"Invalidated existing token for {user_waba}: {token[:8]}...")


def _redis_token_key(token: str) -> str:
    return f"checkin_image:token:{token}"


def _redis_user_key(user_waba: str) -> str:
    return f"checkin_image:user:{user_waba}"


def _redis_used_key(token: str) -> str:
    return f"checkin_image:token_used:{token}"


async def _redis_available() -> bool:
    try:
        return await redis_manager.ping()
    except Exception:
        return False


async def generate_image_attendance_link(user_waba: str) -> str:
    """Generate check-in link with Redis-backed tokens (atomic, TTL), with in-memory fallback."""
    # Start cleanup task if not already running (for in-memory fallback)
    start_cleanup_task()

    token = str(uuid.uuid4())
    expires_at = get_this_moment() + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    expiry_seconds = TOKEN_EXPIRY_MINUTES * 60

    if await _redis_available():
        try:
            async with redis_manager.get_client() as client:
                # Invalidate previous token for this user if exists by marking used
                prev_token = await client.get(_redis_user_key(user_waba))
                if prev_token:
                    # Mark previous token as used (idempotent) and let its TTL expire naturally
                    await client.set(
                        _redis_used_key(prev_token), "1", ex=expiry_seconds
                    )

                # Store new token JSON with TTL
                token_data = {
                    "user_waba": user_waba,
                    "created_at": get_this_moment().isoformat(),
                }
                await client.setex(
                    _redis_token_key(token),
                    expiry_seconds,
                    __import__("json").dumps(token_data),
                )
                await client.setex(_redis_user_key(user_waba), expiry_seconds, token)

            checkin_url = f"{base_url}/attendance-via-image/{token}/"
            logging.info(
                f"Generated worker checkin image URL (Redis) for {user_waba}: {checkin_url}"
            )
            logging.info(f"Token TTL: {expiry_seconds}s")
            return checkin_url
        except Exception as e:
            logging.error(
                f"Redis unavailable during token generation, falling back to memory: {e}"
            )

    # Fallback to in-memory (single-process safety only)
    invalidate_existing_tokens_for_user(user_waba)
    with TOKENS_LOCK:
        CHECKIN_TOKENS[token] = {
            "user_waba": user_waba,
            "expires_at": expires_at,
            "used": False,
            "created_at": get_this_moment(),
        }
    checkin_url = f"{base_url}/attendance-via-image/{token}/"
    logging.info(
        f"Generated worker checkin image URL (in-memory) for {user_waba}: {checkin_url}"
    )
    return checkin_url


async def validate_token(token: str) -> Dict[str, Any]:
    """Validate token and return token data or raise appropriate exception.
    Uses Redis-backed tokens if available; falls back to in-memory store."""
    # Basic token format validation
    if not token:
        logging.warning("Empty token provided")
        raise HTTPException(status_code=400, detail="Token is required")
    if len(token) != 36 or token.count("-") != 4:
        logging.warning(
            f"Invalid token format: {token[:8] if len(token) >= 8 else token}..."
        )
        raise HTTPException(status_code=400, detail="Invalid token format")

    if await _redis_available():
        try:
            async with redis_manager.get_client() as client:
                raw = await client.get(_redis_token_key(token))
                if not raw:
                    logging.warning(
                        f"Token not found or expired in Redis: {token[:8]}..."
                    )
                    raise HTTPException(
                        status_code=400, detail="Invalid or expired token"
                    )

                import json

                token_entry = json.loads(raw)
                # Check used marker
                used_marker = await client.get(_redis_used_key(token))
                if used_marker:
                    logging.warning(f"Token already used (Redis): {token[:8]}...")
                    raise HTTPException(
                        status_code=400,
                        detail="This check-in link has already been used",
                    )

                # TTL check for information
                ttl_sec = await client.ttl(_redis_token_key(token))
                minutes_left = ttl_sec / 60 if ttl_sec and ttl_sec > 0 else 0
                logging.info(
                    f"Token validated (Redis): {token[:8]}... (expires in {minutes_left:.1f} minutes)"
                )
                return token_entry
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Redis error during validate_token, falling back: {e}")

    # Fallback to in-memory validation
    current_time = get_this_moment()
    with TOKENS_LOCK:
        if token not in CHECKIN_TOKENS:
            logging.warning(f"Token not found in memory: {token[:8]}...")
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        token_entry = CHECKIN_TOKENS[token].copy()
    if token_entry.get("used", False):
        used_at = token_entry.get("used_at") or token_entry.get("invalidated_at")
        used_at_str = (
            used_at.strftime("%Y-%m-%d %H:%M:%S") if used_at else "unknown time"
        )
        logging.warning(f"Token already used: {token[:8]}... (used at: {used_at_str})")
        raise HTTPException(
            status_code=400, detail="This check-in link has already been used"
        )
    if current_time > token_entry["expires_at"]:
        logging.warning(
            f"Token expired: {token[:8]}... (expired at {token_entry['expires_at']})"
        )
        with TOKENS_LOCK:
            if token in CHECKIN_TOKENS:
                CHECKIN_TOKENS[token]["expired"] = True
        raise HTTPException(
            status_code=400,
            detail="Check-in link has expired. Please request a new one.",
        )
    time_remaining = token_entry["expires_at"] - current_time
    logging.info(
        f"Token validated successfully (memory): {token[:8]}... (expires in {time_remaining.total_seconds()/60:.1f} minutes)"
    )
    return token_entry


@router.get("/attendance-via-image/{token}/", response_class=HTMLResponse)
async def create_check_in_image_link_with_token(request: Request, token: str):
    try:
        token_entry = await validate_token(token)
        user_waba = token_entry.get("user_waba", "")

        # Calculate time remaining
        minutes_remaining = 0
        try:
            if await _redis_available():
                async with redis_manager.get_client() as client:
                    ttl_sec = await client.ttl(_redis_token_key(token))
                    minutes_remaining = max(0, int((ttl_sec or 0) / 60))
            else:
                time_remaining = CHECKIN_TOKENS[token]["expires_at"] - get_this_moment()
                minutes_remaining = max(0, int(time_remaining.total_seconds() / 60))
        except Exception:
            minutes_remaining = TOKEN_EXPIRY_MINUTES

        logging.info(
            f"📱 Serving image check-in page for {user_waba} (token expires in {minutes_remaining} minutes)"
        )

        return templates.TemplateResponse(
            "attendance_via_image.html",
            {
                "request": request,
                "token": token,
                "user_waba": user_waba,
                "minutes_remaining": minutes_remaining,
            },
        )

    except HTTPException as e:
        # Return user-friendly error page
        error_message = "連結無效或已過期，請重新獲取。"
        if "already been used" in str(e.detail):
            error_message = "此簽到連結已使用過，請重新獲取。"
        elif "expired" in str(e.detail):
            error_message = "簽到連結已過期，請重新獲取"
        elif "Invalid token format" in str(e.detail):
            error_message = "連結格式錯誤，請重新獲取。"

        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>簽到錯誤</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        padding: 2rem;
                        max-width: 600px;
                        margin: 0 auto;
                        background-color: #f5f5f5;
                        text-align: center;
                    }}
                    .error-container {{
                        background: white;
                        padding: 2rem;
                        border-radius: 12px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        border-left: 4px solid #f44336;
                    }}
                    .error-icon {{ font-size: 3rem; margin-bottom: 1rem; }}
                    h1 {{ color: #c62828; margin-bottom: 1rem; }}
                    p {{ color: #666; margin-bottom: 1.5rem; }}
                    .instructions {{
                        background-color: #fff3e0;
                        padding: 1rem;
                        border-radius: 8px;
                        margin-top: 1rem;
                        text-align: left;
                    }}
                </style>
            </head>
            <body>
                <div class="error-container">
                    <div class="error-icon">❌</div>
                    <h1>連結失效</h1>
                    <p>{error_message}</p>
                    <div class="instructions">
                        <strong>📱 如何獲取新的簽到連結: </strong>
                        <ol style="margin-top: 0.5rem;">
                            <li>返回 WhatsApp</li>
                            <li>發送「上傳圖片來簽到」</li>
                            <li>點擊新的簽到連結</li>
                        </ol>
                    </div>
                </div>
            </body>
            </html>
        """,
            status_code=400,
        )


# Add a debug endpoint to check token status (remove in production)
@router.get("/debug/image-tokens/")
async def debug_image_tokens():
    if not os.getenv("DEBUG_MODE", "").lower() == "true":
        raise HTTPException(status_code=404, detail="Not found")

    current_time = get_this_moment()
    active_tokens = []

    with TOKENS_LOCK:
        for token, data in CHECKIN_TOKENS.items():
            time_remaining = data["expires_at"] - current_time
            active_tokens.append(
                {
                    "token": token[:8] + "...",
                    "user_waba": data["user_waba"][-4:] if data["user_waba"] else "N/A",
                    "used": data.get("used", False),
                    "expires_in_minutes": int(time_remaining.total_seconds() / 60),
                    "created_at": (
                        data["created_at"].isoformat()
                        if "created_at" in data
                        else "N/A"
                    ),
                    "used_at": (
                        data.get("used_at", {}).isoformat()
                        if data.get("used_at")
                        else "N/A"
                    ),
                    "expired": data.get("expired", False),
                }
            )

    return {
        "total_tokens": len(CHECKIN_TOKENS),
        "active_tokens": len(
            [t for t in CHECKIN_TOKENS.values() if not t.get("used", False)]
        ),
        "tokens": active_tokens[:10],
    }


import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from src.models.attendance_via_image_model import (AttendanceViaImageModel,
                                                   GoogleMapsScreenshot,
                                                   SiteImage)


def extract_gps_from_exif(image_bytes: bytes):
    """Extract latitude and longitude from image EXIF metadata"""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        exif_data = image._getexif()

        if not exif_data:
            raise ValueError("No EXIF metadata found in image")

        gps_info = {}
        for tag, value in exif_data.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                for t in value:
                    gps_tag = GPSTAGS.get(t, t)
                    gps_info[gps_tag] = value[t]

        if not gps_info:
            raise ValueError("No GPS data found in image EXIF")

        def convert_to_degrees(value):
            d, m, s = value
            return (
                float(d[0]) / float(d[1])
                + (float(m[0]) / float(m[1]) / 60.0)
                + (float(s[0]) / float(s[1]) / 3600.0)
            )

        lat = convert_to_degrees(gps_info["GPSLatitude"])
        if gps_info.get("GPSLatitudeRef") != "N":
            lat = -lat

        lon = convert_to_degrees(gps_info["GPSLongitude"])
        if gps_info.get("GPSLongitudeRef") != "E":
            lon = -lon

        return str(lat), str(lon)

    except Exception as e:
        raise ValueError(f"Failed to extract GPS from EXIF: {str(e)}")


async def verify_token(token: str) -> str:
    """Verify token and return user_waba"""
    try:
        # Use the existing token validation logic
        token_entry = await validate_token(token)
        user_waba = token_entry.get("user_waba", "")

        # For now, use WhatsApp number as user_waba
        # In a real implementation, you'd look up the user by WhatsApp number
        return user_waba
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid token")


@router.post("/attendance-via-image/")
async def submit_attendance_via_image(token: str = Form(...),
                                      project_id: str = Form(...),
                                      timestamp: datetime = Form(...),
                                      site_image: UploadFile = File(...),
                                      screenshot: UploadFile = File(...)):

    try:

        user_waba = await verify_token(token)
        logging.info(f"🔄 Processing check-in for attendance: {user_waba}")
        logging.info(f"Timestamp: {timestamp}")

        site_image_contents = await site_image.read()

        try:
            latitude, longitude = extract_gps_from_exif(site_image_contents)
        except Exception as e:
            logger.warning(f"Could not extract GPS from EXIF: {str(e)}")
            latitude, longitude = "0.0", "0.0"

        screenshot_contents = None
        if screenshot:
            screenshot_contents = await screenshot.read()

        # Save images to GridFS and get file IDs
        import uuid

        from infrastructure.database.database_connection import save_image_bytes_to_gridfs

        # Generate unique filenames
        site_image_filename = f"attendance_site_{user_waba}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        screenshot_filename = f"attendance_screenshot_{user_waba}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"

        # Save site image to GridFS
        site_image_metadata = {
            "user_waba": user_waba,
            "project_id": project_id,
            "attendance_type": "site_image",
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": timestamp,
            "original_filename": site_image.filename,
            "content_type": site_image.content_type,
        }
        site_image_gridfs_id = await save_image_bytes_to_gridfs(
            site_image_contents, site_image_filename, site_image_metadata
        )

        # Save screenshot to GridFS (if provided)
        screenshot_gridfs_id = None
        if screenshot_contents:
            screenshot_metadata = {
                "user_waba": user_waba,
                "project_id": project_id,
                "attendance_type": "google_maps_screenshot",
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": timestamp,
                "original_filename": screenshot.filename,
                "content_type": screenshot.content_type,
            }
            screenshot_gridfs_id = await save_image_bytes_to_gridfs(
                screenshot_contents, screenshot_filename, screenshot_metadata
            )

        # Create SiteImage object with GridFS ID
        site_image_obj = SiteImage(
            image_file_id=site_image_gridfs_id,  # GridFS file ID
            image_timestamp=timestamp,
            lan=latitude,
            lon=longitude,
            accuracy="0",  # Default accuracy for image-based attendance
            is_accepted=True,  # Accept for now to enable conversion and WhatsApp notification
        )

        # Create GoogleMapsScreenshot object (required) with GridFS ID
        google_maps_screenshot_obj = GoogleMapsScreenshot(
            image_file_id=screenshot_gridfs_id,  # GridFS file ID
            screenshot_timestamp=timestamp,
            is_accepted=True,  # Accept for now to enable conversion and WhatsApp notification
        )

        from src.utils.standardization_helpers import \
            validate_mobile_from_whatsapp

        sender_info = await validate_mobile_from_whatsapp(user_waba)

        if not sender_info:
            logger.error(f"User not found for user_waba: {user_waba}")
            raise HTTPException(status_code=404, detail="User not found")

        user_id = str(sender_info.id)

        # Process through service layer
        result = await AttendanceViaImageModel.upload_image_attendance_info_to_database(
            user_id=user_id,
            user_waba=user_waba,
            project_id=project_id,
            site_image=site_image_obj,
            google_maps_screenshot=google_maps_screenshot_obj,
        )

        logger.info(
            f"Attendance submitted successfully for user {user_id}, project {project_id}"
        )
        return {
            "status": "success",
            "message": "Attendance recorded successfully",
            "attendance_id": str(result.id),
            "timestamp": timestamp,
        }

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting attendance: {str(e)}")
        raise HTTPException(status_code=500, detail=f"簽到失敗: {str(e)}")




@router.get("/attendance-images/{image_file_id}/")
async def get_attendance_image(image_file_id: str):

    try:
        from infrastructure.database.database_connection import get_file_from_gridfs

        if not image_file_id or len(image_file_id) != 24:
            raise HTTPException(status_code=400, detail="Invalid image file ID format")

        try:
            from bson import ObjectId

            ObjectId(image_file_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ObjectId format")

        filename, content = await get_file_from_gridfs(image_file_id)

        max_file_size = 50 * 1024 * 1024  # 50MB limit
        if len(content) > max_file_size:
            logger.warning(
                f"Image {image_file_id} exceeds size limit: {len(content)} bytes"
            )
            raise HTTPException(status_code=413, detail="Image file too large")

        content_type = "image/jpeg"  # Default to JPEG
        if filename.lower().endswith((".png", ".PNG")):
            content_type = "image/png"
        elif filename.lower().endswith((".gif", ".GIF")):
            content_type = "image/gif"
        elif filename.lower().endswith((".webp", ".WEBP")):
            content_type = "image/webp"

        def iter_content():
            yield content

        return StreamingResponse(
            iter_content(),
            media_type=content_type,
            headers={
                "Content-Disposition": f"inline; filename={filename}",
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                "X-Content-Type-Options": "nosniff",  # Security header
                "X-Frame-Options": "DENY",  # Security header
            },
        )

    except HTTPException:
        # Re-raise HTTP exceptions (like 404, 400)
        raise
    except Exception as e:
        logger.error(f"Error retrieving attendance image {image_file_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image")
