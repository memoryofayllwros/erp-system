# check_in_routes.py
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from src.models.attendance_record_model import AttendanceRecord
from src.routes.user_routes import get_current_user
from infrastructure.redis_connection.redis_manager import redis_manager
from src.utils.datetime_standarization_helpers import get_this_moment

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

ENABLE_WABA_NOTIFICATIONS = (
    os.getenv("ENABLE_WABA_NOTIFICATIONS", "true").lower() == "true"
)

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
    return f"gps_attendance:token:{token}"


def _redis_user_key(user_waba: str) -> str:
    return f"gps_attendance:user:{user_waba}"


def _redis_used_key(token: str) -> str:
    return f"gps_attendance:token_used:{token}"


async def _redis_available() -> bool:
    try:
        return await redis_manager.ping()
    except Exception:
        return False


async def generate_gps_attendance_link(user_waba: str) -> str: #old name: generate_check_in_gps_link
    """Generate GPS attendance link with Redis-backed tokens (atomic, TTL), with in-memory fallback."""
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

            gps_attendance_url = f"{base_url}/attendance-via-gps/{token}/"
            logging.info(
                f"Generated worker GPS attendance URL (Redis) for {user_waba}: {gps_attendance_url}"
            )
            logging.info(f"Token TTL: {expiry_seconds}s")
            return gps_attendance_url
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
    gps_attendance_url = f"{base_url}/attendance-via-gps/{token}/"
    logging.info(
        f"Generated worker GPS attendance URL (in-memory) for {user_waba}: {gps_attendance_url}"
    )
    return gps_attendance_url


class PostGpsAttendanceData(BaseModel):
    token: str
    latitude: float = Field(
        ..., ge=-90, le=90, description="Latitude between -90 and 90"
    )
    longitude: float = Field(
        ..., ge=-180, le=180, description="Longitude between -180 and 180"
    )
    accuracy: float = Field(..., ge=0, description="GPS accuracy in meters")
    timestamp: datetime = Field(default_factory=get_this_moment, description="Timestamp in Hong Kong timezone")
    project_id: Optional[str] = None

    @field_validator("latitude", "longitude", "accuracy")
    @classmethod
    def validate_coordinates(cls, v: float) -> float:
        """Validate coordinate values and handle edge cases"""
        if v is None or str(v).lower() in [
            "nan",
            "inf",
            "-inf",
            "infinity",
            "-infinity",
        ]:
            raise ValueError(f"Invalid coordinate value: {v}")
        return v


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
                        detail="This GPS attendance link has already been used",
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
            status_code=400, detail="This GPS attendance link has already been used"
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
            detail="GPS attendance link has expired. Please request a new one.",
        )
    time_remaining = token_entry["expires_at"] - current_time
    logging.info(
        f"Token validated successfully (memory): {token[:8]}... (expires in {time_remaining.total_seconds()/60:.1f} minutes)"
    )
    return token_entry


@router.post("/attendance-via-gps/")
async def worker_gps_attendance_without_token(data: PostGpsAttendanceData):
    """Enhanced GPS attendance endpoint with better error handling and race condition prevention"""
    try:
        # Validate token first
        token_entry = await validate_token(data.token)

        # Double-check and atomically mark token as used to prevent race conditions
        current_time = get_this_moment()
        user_waba_from_token = token_entry.get("user_waba", "")

        # Prefer Redis atomic mark-if-unused; fallback to in-memory lock
        marked_used = False
        if await _redis_available():
            try:
                async with redis_manager.get_client() as client:
                    # SETNX used marker; if already set, someone used it
                    result = await client.set(
                        _redis_used_key(data.token),
                        "1",
                        nx=True,
                        ex=TOKEN_EXPIRY_MINUTES * 60,
                    )
                    if not result:
                        logging.warning(
                            f"Token was used by another request (Redis): {data.token[:8]}..."
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="This GPS attendance link has already been used",
                        )
                    # Clean user->token mapping if matches
                    existing = await client.get(_redis_user_key(user_waba_from_token))
                    if existing == data.token:
                        await client.delete(_redis_user_key(user_waba_from_token))
                    marked_used = True
            except HTTPException:
                raise
            except Exception as e:
                logging.error(
                    f"Redis error during atomic mark used, falling back to memory: {e}"
                )

        if not marked_used:
            with TOKENS_LOCK:
                if data.token not in CHECKIN_TOKENS:
                    logging.error(
                        f"Token disappeared during processing: {data.token[:8]}..."
                    )
                    raise HTTPException(
                        status_code=400, detail="Token is no longer valid"
                    )
                current_token_data = CHECKIN_TOKENS[data.token]
                if current_token_data.get("used", False):
                    logging.warning(
                        f"Token was used by another request: {data.token[:8]}..."
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="This GPS attendance link has already been used",
                    )
                if current_time > current_token_data["expires_at"]:
                    logging.warning(
                        f"Token expired during processing: {data.token[:8]}..."
                    )
                    raise HTTPException(
                        status_code=400, detail="GPS attendance link has expired"
                    )
                CHECKIN_TOKENS[data.token]["used"] = True
                CHECKIN_TOKENS[data.token]["used_at"] = current_time
                user_waba_from_token = current_token_data["user_waba"]

        # Store GPS attendance data
        CHECKIN_LOGS.append(
            {
                "user_waba": user_waba_from_token,
                "lat": data.latitude,
                "lon": data.longitude,
                "accuracy": data.accuracy,
                "timestamp": data.timestamp,
                "processed_at": get_this_moment(),
                "project_id": data.project_id,
            }
        )

        try:
            from src.models.attendance_via_gps_model import AttendanceViaGpsModel, GpsAttendanceInfo

            gps_info = GpsAttendanceInfo(
                timestamp=data.timestamp,
                lan=str(data.latitude),
                lon=str(data.longitude),
                accuracy=str(data.accuracy),
            )
            logging.info(f"GPS info: timestamp={data.timestamp} lan='{data.latitude}' lon='{data.longitude}' accuracy='{data.accuracy}'")

            from src.utils.standardization_helpers import validate_mobile_from_whatsapp
            user_mobile_info = await validate_mobile_from_whatsapp(user_waba_from_token)
            user_id = str(user_mobile_info.id)
            logging.info(f"User ID: {user_id}")

            attendance_result = await AttendanceViaGpsModel.add_gps_attendance_info(
                user_id=user_id,
                user_waba=user_waba_from_token,
                project_id=data.project_id,
                gps_attendance=gps_info
            )
            logging.info(f"GPS attendance added successfully: {attendance_result}")

        except Exception as attendance_error:
            logging.error(
                f"❌ Error in automatic attendance processing: {attendance_error}"
            )
            # Send error message to user
            try:
                error_message = "簽到位置已記錄，但處理時發生問題。請稍後再試。"
#                await send_whatsapp_message_back(error_message, user_waba_from_token)
            except Exception as msg_error:
                logging.error(f"❌ Failed to send error message: {msg_error}")

        return {
            "status": "success",
            "message": "GPS attendance completed successfully",
            "timestamp": get_this_moment().isoformat(),
        }

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logging.error(f"❌ Unexpected error in GPS attendance: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error during GPS attendance"
        )


@router.get("/attendance-via-gps/{token}/", response_class=HTMLResponse)
async def create_gps_attendance_link_with_token(request: Request, token: str):
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
            f"📱 Serving GPS attendance page for {user_waba} (token expires in {minutes_remaining} minutes)"
        )

        return templates.TemplateResponse(
            "attendance_via_gps.html",
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
                <title>GPS 簽到錯誤</title>
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
                        <strong>📱 如何獲取新的 GPS 簽到連結: </strong>
                        <ol style="margin-top: 0.5rem;">
                            <li>返回 WhatsApp</li>
                            <li>發送「簽到」或「打卡」</li>
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
@router.get("/debug/tokens/")
async def debug_tokens():
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


@router.post("/trigger-pdf-update/{project_id}/")
async def trigger_attendance_pdf_update(
    project_id: str, force_regenerate: bool = False
):
    """
    Manually trigger attendance PDF update for a project

    Args:
        project_id: Project ID to update
        force_regenerate: Force regeneration even if no changes detected
    """
    try:
        # Validate project exists
        from src.models.project_model import Project
        from temporal_app.client import get_temporal_client

        project = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Trigger Temporal.io workflow
        client = await get_temporal_client()

        handle = await client.start_workflow(
            "AttendancePDFUpdateWorkflow",
            args=[project_id, force_regenerate],
            id=f"manual-pdf-update-{project_id}-{get_this_moment().strftime('%Y%m%d%H%M%S')}",
            task_queue="attendance-task-queue",
        )

        return {
            "status": "success",
            "message": "Attendance PDF update workflow triggered",
            "workflow_id": handle.id,
            "project_id": project_id,
            "project_code": project.project_code,
            "force_regenerate": force_regenerate,
            "triggered_at": get_this_moment().isoformat(),
        }

    except Exception as e:
        logging.error(f"Error triggering PDF update: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger PDF update: {str(e)}"
        )


@router.post("/batch-trigger-pdf-updates/")
async def batch_trigger_attendance_pdf_updates(
    project_ids: List[str], force_regenerate: bool = False
):
    """
    Manually trigger attendance PDF updates for multiple projects
    """
    try:
        # Validate projects exist
        from src.models.project_model import Project
        from temporal_app.client import get_temporal_client

        valid_projects = []
        for project_id in project_ids:
            try:
                project = await Project.find_one(
                    Project.id == ObjectId(project_id), Project.deleted_at == None
                )
                if project:
                    valid_projects.append(project_id)
            except Exception:
                continue

        if not valid_projects:
            raise HTTPException(status_code=400, detail="No valid project IDs provided")

        # Trigger batch workflow
        client = await get_temporal_client()

        handle = await client.start_workflow(
            "BatchAttendancePDFUpdateWorkflow",
            args=[valid_projects, force_regenerate],
            id=f"batch-pdf-update-{get_this_moment().strftime('%Y%m%d%H%M%S')}",
            task_queue="attendance-task-queue",
        )

        return {
            "status": "success",
            "message": "Batch attendance PDF update workflow triggered",
            "workflow_id": handle.id,
            "total_projects": len(valid_projects),
            "valid_project_ids": valid_projects,
            "force_regenerate": force_regenerate,
            "triggered_at": get_this_moment().isoformat(),
        }

    except Exception as e:
        logging.error(f"Error triggering batch PDF updates: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger batch PDF updates: {str(e)}"
        )


@router.get("/pdf-update-status/{workflow_id}/")
async def get_pdf_update_status(
    workflow_id: str, current_user=Depends(get_current_user)
):
    """
    Get the status of a PDF update workflow
    """
    try:
        from temporal_app.client import get_temporal_client

        client = await get_temporal_client()

        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)

        # Get workflow status
        status = await handle.describe()

        return {
            "workflow_id": workflow_id,
            "status": status.status.name,
            "execution_time": (
                status.execution_time.isoformat() if status.execution_time else None
            ),
            "close_time": status.close_time.isoformat() if status.close_time else None,
            "run_id": status.run_id,
            "workflow_type": status.workflow_type,
        }

    except Exception as e:
        logging.error(f"Error getting workflow status: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get workflow status: {str(e)}"
        )


@router.get("/shift-analysis/{project_id}/{year}/{month}/")
async def get_project_shift_analysis(
    project_id: str, year: int, month: int, current_user=Depends(get_current_user)
):
    """
    Get detailed shift analysis for a specific project and month

    Returns:
        - Full day shift workers count
        - Daily breakdown
        - Worker details
    """
    try:
        # Validate month
        if month < 1 or month > 12:
            raise HTTPException(
                status_code=400, detail="Month must be between 1 and 12"
            )

        # Validate year
        current_year = get_this_moment().year
        if year < 2020 or year > current_year + 1:
            raise HTTPException(
                status_code=400,
                detail=f"Year must be between 2020 and {current_year + 1}",
            )

        # Get shift analysis
        analysis_result = await AttendanceRecord.get_project_shift_analysis(
            project_id=project_id, year=year, month=month
        )

        if "error" in analysis_result:
            raise HTTPException(
                status_code=500, detail=f"Analysis failed: {analysis_result['error']}"
            )

        return {
            "status": "success",
            "data": analysis_result,
            "requested_at": get_this_moment().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in get_project_shift_analysis: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get shift analysis: {str(e)}"
        )

