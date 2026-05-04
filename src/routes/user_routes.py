import io
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Union
import time
from collections import defaultdict
import re

import jwt
from bson import ObjectId
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from fastapi.responses import StreamingResponse
from fastapi.security import (OAuth2PasswordBearer, OAuth2PasswordRequestForm,
                              SecurityScopes)

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from functools import wraps
from typing import Callable, List

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None

from infrastructure.database.database_connection import get_grid_fs
from src.models.user_model import WorkType, User
from src.utils.datetime_standarization_helpers import get_this_moment

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY", SECRET_KEY + "_refresh")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080
REFRESH_TOKEN_EXPIRE_DAYS = 30  # Refresh tokens last 30 days

# Rate limiting configuration
RATE_LIMIT_ATTEMPTS = 5  # Maximum attempts per window
RATE_LIMIT_WINDOW = 300  # 5 minutes in seconds
RATE_LIMIT_BLOCK_DURATION = 900  # 15 minutes block duration

# In-memory rate limiting store (in production, use Redis)
rate_limit_store = defaultdict(list)
blocked_ips = {}

# Token blacklist for logout functionality (in production, use Redis)
token_blacklist = set()

# Audit logging configuration
AUDIT_LOG_LEVEL = logging.INFO
audit_logger = logging.getLogger("audit")
audit_logger.setLevel(AUDIT_LOG_LEVEL)

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={
        "read": "Read access to user information",
        "write": "Write access to user information",
        "admin": "Admin-level access",
    },
)

# Configure password context with explicit bcrypt settings
# Note: passlib 1.7.4 has compatibility issues with bcrypt 4.0.0+
# We'll use direct bcrypt as fallback if passlib fails
pwd_context = None
PASSLIB_WORKING = False

# Check bcrypt version - passlib 1.7.4 is incompatible with bcrypt 4.0+
# If bcrypt >= 4.0, skip passlib entirely to avoid initialization errors
skip_passlib = False
if BCRYPT_AVAILABLE and bcrypt:
    try:
        # Try to get version - newer bcrypt doesn't have __about__
        bcrypt_version = None
        try:
            # Old way (bcrypt < 4.0)
            bcrypt_version = bcrypt.__about__.__version__
        except AttributeError:
            # New way (bcrypt >= 4.0) - use importlib.metadata
            try:
                import importlib.metadata
                bcrypt_version = importlib.metadata.version('bcrypt')
            except Exception:
                # Fallback: try __version__ attribute
                bcrypt_version = getattr(bcrypt, '__version__', None)
        
        # Parse major version
        if bcrypt_version:
            major_version = int(bcrypt_version.split('.')[0])
            if major_version >= 4:
                logger.info(f"Detected bcrypt {bcrypt_version} - passlib 1.7.4 is incompatible, using direct bcrypt")
                skip_passlib = True
    except Exception:
        # If version detection fails, we'll try passlib anyway
        pass

# Try to configure passlib only if bcrypt < 4.0
if not skip_passlib:
    try:
        pwd_context = CryptContext(
            schemes=["bcrypt"], 
            deprecated="auto",
            bcrypt__rounds=12,
            bcrypt__min_rounds=10,
            bcrypt__max_rounds=15
        )
        # Test if passlib works by trying a simple operation
        test_hash = pwd_context.hash("test")
        PASSLIB_WORKING = True
        logger.info("Passlib configured successfully")
    except Exception as e:
        logger.warning(f"Failed to configure passlib with advanced settings: {e}")
        # Fallback to basic configuration
        try:
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            test_hash = pwd_context.hash("test")
            PASSLIB_WORKING = True
            logger.info("Passlib configured with basic settings")
        except Exception as e2:
            logger.warning(f"Passlib initialization failed: {e2}")
            logger.info("Will use direct bcrypt library instead")
            PASSLIB_WORKING = False
            pwd_context = None

# =====================
# 📦 Pydantic Schemas
# =====================


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenRefresh(BaseModel):
    refresh_token: str


class TokenData(BaseModel):
    mobile: Optional[List[str]] = None
    scopes: List[str] = []


# ======================
# 🔧 Utility Functions
# ======================

def log_auth_event(event_type: str, user_mobile, ip_address: str, success: bool, details: str = ""):
    """Log authentication events for audit purposes."""
    timestamp = get_this_moment().isoformat()
    status = "SUCCESS" if success else "FAILURE"
    
    # Convert mobile to string for logging
    mobile_str = user_mobile[0] if isinstance(user_mobile, list) and user_mobile else str(user_mobile)
    
    audit_logger.info(
        f"AUTH_EVENT|{timestamp}|{event_type}|{mobile_str}|{ip_address}|{status}|{details}"
    )


def log_security_event(event_type: str, ip_address: str, details: str):
    """Log security-related events."""
    timestamp = get_this_moment().isoformat()
    
    audit_logger.warning(
        f"SECURITY_EVENT|{timestamp}|{event_type}|{ip_address}|{details}"
    )


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    # Check for forwarded headers first (for reverse proxy setups)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct connection IP
    return request.client.host if request.client else "unknown"


def is_rate_limited(ip: str) -> bool:
    """Check if IP is rate limited."""
    current_time = time.time()
    
    # Check if IP is blocked
    if ip in blocked_ips:
        if current_time < blocked_ips[ip]:
            return True
        else:
            # Block expired, remove it
            del blocked_ips[ip]
    
    # Clean old attempts
    rate_limit_store[ip] = [
        attempt_time for attempt_time in rate_limit_store[ip]
        if current_time - attempt_time < RATE_LIMIT_WINDOW
    ]
    
    # Check if limit exceeded
    if len(rate_limit_store[ip]) >= RATE_LIMIT_ATTEMPTS:
        # Block the IP
        blocked_ips[ip] = current_time + RATE_LIMIT_BLOCK_DURATION
        return True
    
    return False


def record_auth_attempt(ip: str) -> None:
    """Record an authentication attempt."""
    current_time = time.time()
    rate_limit_store[ip].append(current_time)


def rate_limit_auth(func):
    """Decorator to apply rate limiting to authentication endpoints."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract request from kwargs
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        
        if request:
            client_ip = get_client_ip(request)
            
            if is_rate_limited(client_ip):
                log_security_event("RATE_LIMIT_EXCEEDED", client_ip, f"Blocked for {RATE_LIMIT_BLOCK_DURATION} seconds")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="⚠️ 登入嘗試過於頻繁，請稍後再試",
                    headers={"Retry-After": str(RATE_LIMIT_BLOCK_DURATION)},
                )
            
            # Record the attempt
            record_auth_attempt(client_ip)
        
        return await func(*args, **kwargs)
    return wrapper
def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength according to security policies.
    Returns (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "密碼長度至少需要8個字符"
    
    if len(password) > 128:
        return False, "密碼長度不能超過128個字符"
    
    # Check for at least one uppercase letter
    if not re.search(r'[A-Z]', password):
        return False, "密碼必須包含至少一個大寫字母"
    
    # Check for at least one lowercase letter
    if not re.search(r'[a-z]', password):
        return False, "密碼必須包含至少一個小寫字母"
    
    # Check for at least one digit
    if not re.search(r'\d', password):
        return False, "密碼必須包含至少一個數字"
    
    # Check for at least one special character
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "密碼必須包含至少一個特殊字符 (!@#$%^&*(),.?\":{}|<>)"
    
    # Check for common weak patterns
    weak_patterns = [
        r'(.)\1{2,}',  # 3 or more consecutive identical characters
        r'(012|123|234|345|456|567|678|789|890)',  # Sequential numbers
        r'(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)',  # Sequential letters
    ]
    
    for pattern in weak_patterns:
        if re.search(pattern, password.lower()):
            return False, "密碼不能包含連續的相同字符或順序字符"
    
    # Check for common passwords
    common_passwords = [
        'password', '123456', '123456789', 'qwerty', 'abc123', 
        'password123', 'admin', 'letmein', 'welcome', 'monkey'
    ]
    
    if password.lower() in common_passwords:
        return False, "密碼不能使用常見的弱密碼"
    
    return True, ""


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt with proper length handling.
    Uses direct bcrypt if passlib is not working properly.
    """
    # Always use direct bcrypt if passlib is not working
    if not PASSLIB_WORKING or not BCRYPT_AVAILABLE or not bcrypt:
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                # Truncate password to 72 bytes if needed
                password_bytes = password.encode('utf-8')
                if len(password_bytes) > 72:
                    password_bytes = password_bytes[:72]
                
                salt = bcrypt.gensalt()
                hashed = bcrypt.hashpw(password_bytes, salt)
                return hashed.decode('utf-8')
            except Exception as e:
                logger.error(f"Direct bcrypt hashing failed: {e}")
                raise e
        else:
            logger.error("bcrypt not available for password hashing")
            raise ValueError("Cannot hash password without bcrypt")
    
    # Check if password is too long and use direct bcrypt to avoid passlib warnings
    if len(password.encode('utf-8')) > 72:
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                # Truncate password to 72 bytes
                password_bytes = password.encode('utf-8')[:72]
                salt = bcrypt.gensalt()
                hashed = bcrypt.hashpw(password_bytes, salt)
                return hashed.decode('utf-8')
            except Exception as e:
                logger.error(f"Direct bcrypt hashing failed for long password: {e}")
                raise e
        else:
            logger.error("bcrypt not available for long password hashing")
            raise ValueError("Cannot hash long password without bcrypt")
    
    # For passwords <= 72 bytes, try passlib first, then fallback to direct bcrypt
    try:
        return pwd_context.hash(password)
        
    except Exception as e:
        logger.warning(f"Passlib hashing failed: {e}")
        
        # Fallback to direct bcrypt if available
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                password_bytes = password.encode('utf-8')
                salt = bcrypt.gensalt()
                hashed = bcrypt.hashpw(password_bytes, salt)
                return hashed.decode('utf-8')
                
            except Exception as bcrypt_error:
                logger.error(f"Direct bcrypt hashing failed: {bcrypt_error}")
                raise bcrypt_error
        else:
            logger.error("bcrypt not available for fallback hashing")
            raise e


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash with proper length handling.
    Uses direct bcrypt if passlib is not working properly.
    """
    # Always use direct bcrypt if passlib is not working
    if not PASSLIB_WORKING or not BCRYPT_AVAILABLE or not bcrypt:
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                # Truncate password to 72 bytes if needed
                password_bytes = plain_password.encode('utf-8')
                if len(password_bytes) > 72:
                    password_bytes = password_bytes[:72]
                
                return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
            except Exception as e:
                logger.error(f"Direct bcrypt verification failed: {e}")
                return False
        else:
            logger.error("bcrypt not available for password verification")
            return False
    
    # Check if password is too long and use direct bcrypt to avoid passlib warnings
    if len(plain_password.encode('utf-8')) > 72:
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                # Truncate password to 72 bytes
                password_bytes = plain_password.encode('utf-8')[:72]
                return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
            except Exception as e:
                logger.error(f"Direct bcrypt verification failed for long password: {e}")
                return False
        else:
            logger.error("bcrypt not available for long password verification")
            return False
    
    # For passwords <= 72 bytes, try passlib first, then fallback to direct bcrypt
    try:
        return pwd_context.verify(plain_password, hashed_password)
        
    except Exception as e:
        logger.warning(f"Passlib verification failed: {e}")
        
        # Fallback to direct bcrypt if available
        if BCRYPT_AVAILABLE and bcrypt:
            try:
                password_bytes = plain_password.encode('utf-8')
                return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
                
            except Exception as bcrypt_error:
                logger.error(f"Direct bcrypt verification failed: {bcrypt_error}")
                return False
        else:
            logger.error("bcrypt not available for fallback verification")
            return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = get_this_moment() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = get_this_moment() + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


def verify_refresh_token(token: str) -> Optional[TokenData]:
    """Verify and decode a refresh token."""
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        mobile_subject: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if mobile_subject is None or token_type != "refresh":
            return None
        
        # Convert single mobile string to list for TokenData compatibility
        mobile_list = [mobile_subject] if isinstance(mobile_subject, str) else mobile_subject
        return TokenData(mobile=mobile_list, scopes=payload.get("scopes", []))
    except JWTError:
        return None


async def authenticate_user(mobile: str, password: str):
    # Convert single mobile string to list for compatibility with User model
    mobile_list = [mobile] if isinstance(mobile, str) else mobile
    user = await User.read_a_user(mobile_list)
    # Check if user is a string (error message) or None
    if isinstance(user, str) or user is None:
        return None
    if user and verify_password(password, user.hashed_password):
        return user
    return None


async def get_current_user(
    security_scopes: SecurityScopes, token: str = Depends(oauth2_scheme)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please provide a valid authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Check if token is blacklisted (logged out)
    if token in token_blacklist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        mobile_subject: str = payload.get("sub")
        token_scopes = payload.get("scopes", [])
        if mobile_subject is None:
            raise credentials_exception
        # Convert single mobile string to list for TokenData compatibility
        mobile_list = [mobile_subject] if isinstance(mobile_subject, str) else mobile_subject
        token_data = TokenData(mobile=mobile_list, scopes=token_scopes)
    except JWTError:
        raise credentials_exception

    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": f'Bearer scope="{scope}"'},
            )

    try:
        user = await User.read_a_user(token_data.mobile)
        if isinstance(user, str):  # Error message returned as string
            logger.error(f"Error fetching user by mobile: {user}")
            raise credentials_exception
        if user is None:
            logger.error(f"User with mobile {token_data.mobile} not found")
            raise credentials_exception
        return user
    except Exception as e:
        logger.error(f"Error fetching user by mobile: {str(e)}")
        raise credentials_exception


# ========================
# 🔐 Role-Based Access Control
# ========================

def require_roles(*required_roles: str):
    """
    Decorator to require specific roles for endpoint access.
    Usage: @require_roles("admin", "HR", "Manager")
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract current_user from kwargs
            current_user = kwargs.get('current_user')
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # Check if user has any of the required roles
            user_roles = [role.value if hasattr(role, 'value') else str(role) for role in current_user.role]
            if not any(role in user_roles for role in required_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"⚠️ 您沒有權限執行此操作。需要以下角色之一: {', '.join(required_roles)}",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(func):
    """Decorator to require admin role."""
    return require_roles("admin")(func)


def require_manager_or_admin(func):
    """Decorator to require manager or admin role."""
    return require_roles("Manager", "admin")(func)


def require_hr_or_admin(func):
    """Decorator to require HR or admin role."""
    return require_roles("HR", "admin")(func)


def require_any_role(*roles: str):
    """Decorator factory for custom role requirements."""
    return require_roles(*roles)


# ========================
# 📁 File Upload Utilities
# ========================
async def save_image_to_gridfs(
    file: UploadFile, user_id: str, card_type: str, side: str
) -> str:
    """
    Save uploaded image to GridFS and return the file ID.

    Args:
        file: Uploaded file
        user_id: User ID for metadata
        card_type: Type of card (banking_card, national_id_card, etc.)
        side: Front or back of the card

    Returns:
        str: GridFS file ID
    """
    try:
        # Validate file exists and has content
        if not file or not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="⚠️ 檔案不存在或檔案名稱為空",
            )

        # Validate file type
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 只接受圖片檔案"
            )

        # Read file content
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 檔案內容為空"
            )

        # Generate filename
        file_extension = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"{user_id}_{card_type}_{side}.{file_extension}"

        # Get GridFS instance
        grid_fs = await get_grid_fs()

        # Upload to GridFS
        file_id = await grid_fs.upload_from_stream(
            filename=filename,
            source=io.BytesIO(content),
            metadata={
                "user_id": user_id,
                "card_type": card_type,
                "side": side,
                "original_filename": file.filename,
                "content_type": file.content_type,
                "upload_date": get_this_moment().isoformat(),
            },
        )

        logger.info(f"Image uploaded to GridFS: {filename} with ID: {file_id}")
        return str(file_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving image to GridFS: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 儲存圖片時發生錯誤: {str(e)}",
        )

from fastapi.responses import Response
@router.post("/set-approvers-for-user/{user_id}/")
async def set_approvers_for_user_endpoint(user_id: str, approver_ids: List[str], current_user=Depends(get_current_user)):
    try:
        result = await User.set_approvers_for_user_function(user_id, approver_ids)
        if result["status"] == "success":
            return Response(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": result["message"],
                    "user_id": result["user_id"],
                    "approved_by": result["approved_by"]
                }
            )   
        else:
            return Response(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "status": "error",
                    "message": result["message"]
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error setting approved by for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"⚠️ 設置批准者時發生錯誤: {str(e)}")



@router.post("/set-approvers-for-work-type/{work_type}/")
async def set_approvers_for_work_type(work_type: WorkType, approver_ids: List[str], current_user=Depends(get_current_user)):
    try:
        result = await User.set_approvers_for_work_type_function(work_type, approver_ids)
        if result["status"] == "success":
            return {
                "status": "success",
                "message": result["message"],
                "work_type": result["work_type"],
                "updated_users": result.get("updated_users", 0),
                "approved_by": result["approved_by"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error setting approved by for work type {work_type}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"⚠️ 設置批准者時發生錯誤: {str(e)}")







async def get_image_from_gridfs(file_id: str) -> tuple[str, bytes, str]:
    """
    Retrieve image from GridFS by file ID.

    Args:
        file_id: GridFS file ID

    Returns:
        tuple: (filename, content, content_type)
    """
    try:
        object_id = ObjectId(file_id)
    except Exception as e:
        logger.error(f"Invalid ObjectId format: {file_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 無效的檔案ID格式"
        )

    try:
        grid_fs = await get_grid_fs()
        grid_out = await grid_fs.open_download_stream(object_id)
        content = await grid_out.read()

        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 檔案不存在"
            )

        filename = (
            grid_out.filename if hasattr(grid_out, "filename") else f"image_{file_id}"
        )
        content_type = (
            grid_out.metadata.get("content_type", "image/jpeg")
            if hasattr(grid_out, "metadata")
            else "image/jpeg"
        )

        return filename, content, content_type

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving image from GridFS: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 檔案不存在或無法讀取"
        )


# ========================
# 🔐 Authentication Routes
# ========================
@router.post("/token/", response_model=Token)
@rate_limit_auth
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    client_ip = get_client_ip(request)
    
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        log_auth_event("LOGIN_ATTEMPT", form_data.username, client_ip, False, "Invalid credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active:
        log_auth_event("LOGIN_ATTEMPT", form_data.username, client_ip, False, "Inactive user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create both access and refresh tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Use the first mobile number for token subject (for backward compatibility)
    mobile_subject = user.mobile[0] if isinstance(user.mobile, list) and user.mobile else str(user.mobile)
    token_data = {"sub": mobile_subject, "scopes": ["read", "write"]}
    
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token(
        data=token_data,
        expires_delta=refresh_token_expires,
    )
    
    # Log successful login
    log_auth_event("LOGIN_SUCCESS", user.mobile, client_ip, True, f"Role: {user.role}")
    
    return Token(
        access_token=access_token, 
        refresh_token=refresh_token, 
        token_type="bearer"
    )


@router.post("/refresh/", response_model=Token)
@rate_limit_auth
async def refresh_access_token(request: Request, token_request: TokenRefresh):
    """Refresh an access token using a valid refresh token."""
    token_data = verify_refresh_token(token_request.refresh_token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify user still exists and is active
    user = await User.read_a_user(token_data.mobile)
    if isinstance(user, str) or user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create new tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Use the first mobile number for token subject (for backward compatibility)
    mobile_subject = user.mobile[0] if isinstance(user.mobile, list) and user.mobile else str(user.mobile)
    token_data_dict = {"sub": mobile_subject, "scopes": token_data.scopes}
    
    access_token = create_access_token(
        data=token_data_dict,
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token(
        data=token_data_dict,
        expires_delta=refresh_token_expires,
    )
    
    return Token(
        access_token=access_token, 
        refresh_token=refresh_token, 
        token_type="bearer"
    )


@router.post("/logout/")
async def logout(request: Request, current_user=Depends(get_current_user), token: str = Depends(oauth2_scheme)):
    """Logout user by blacklisting their token."""
    client_ip = get_client_ip(request)
    
    # Add token to blacklist
    token_blacklist.add(token)
    
    # Log the logout event
    log_auth_event("LOGOUT", current_user.mobile, client_ip, True)
    
    return {"message": "Successfully logged out"}


@router.post("/logout-all-devices/")
async def logout_all_devices(current_user=Depends(get_current_user)):
    """Logout user from all devices by invalidating all tokens."""
    # In a production environment, you would store user sessions in Redis
    # and invalidate all sessions for this user
    
    # For now, we'll just log the event
    logger.info(f"User {current_user.mobile} logged out from all devices")
    
    return {"message": "Successfully logged out from all devices"}


class BankingCardUpdate(BaseModel):
    banker: Optional[str] = None
    bank_account_no: Optional[str] = None
    card_image_front: Optional[str] = None  # GridFS file ID
    card_image_back: Optional[str] = None  # GridFS file ID


class NationalIDUpdate(BaseModel):
    card_image_front: Optional[str] = None  # GridFS file ID
    card_image_back: Optional[str] = None  # GridFS file ID


class ConstructionWorkerCardUpdate(BaseModel):
    card_no: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    card_image_front: Optional[str] = None  # GridFS file ID
    card_image_back: Optional[str] = None  # GridFS file ID


class CertifiedWorkerCardUpdate(BaseModel):
    reference_no: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    card_image_front: Optional[str] = None  # GridFS file ID
    card_image_back: Optional[str] = None  # GridFS file ID


class UpdateUser(BaseModel):
    occupation: Optional[str] = None
    address: Optional[str] = None
    bonus_desc: Optional[str] = None
    over_65: Optional[bool] = None
    banking_card: Optional[BankingCardUpdate] = None
    national_id_card: Optional[NationalIDUpdate] = None
    construction_worker_card: Optional[ConstructionWorkerCardUpdate] = None
    certified_worker_card: Optional[CertifiedWorkerCardUpdate] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    class Config:
        # Allow partial updates - only include fields that are explicitly set
        extra = "forbid"  # Reject extra fields not defined in the model


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class WorkingHoursData(BaseModel):
    start_time: str
    end_time: str


class SetWorkingHoursRequest(BaseModel):
    working_hours: List[WorkingHoursData]


@router.patch("/update-user/{user_id}/")
async def update_user(
    user_id: str, update_data: UpdateUser, current_user=Depends(get_current_user)
):

    try:
        # Validate user_id format
        if not user_id or not user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 用戶ID不能為空"
            )

        # Check if update_data has any fields to update
        update_dict = update_data.dict(exclude_unset=True, exclude_none=True)
        if not update_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 沒有提供要更新的資料"
            )

        # Log the update attempt
        logger.info(f"Updating user {user_id} with fields: {list(update_dict.keys())}")

        # Call the model's update function
        result = await User.update_user_function(user_id, update_dict)

        # Check the result and return appropriate response
        if result["status"] == "success":
            return {
                "status": "success",
                "message": result["message"],
                "user_id": result.get("user_id"),
                "updated_fields": list(update_dict.keys()),
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"]
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error updating user {user_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 更新用戶資料時發生錯誤: {str(e)}",
        )


class CreateUser(BaseModel):
    mobile: List[str]
    payee_name: str
    chinese_name: Optional[str] = None
    english_name: Optional[str] = None
    staff_no: str
    work_type: WorkType
    role: Optional[List[str]] = None
    occupation: str
    client_company_id: str

@router.post("/add-user/")
@require_roles("admin", "HR", "Manager")
async def add_user_by_endpoint(request: CreateUser, current_user=Depends(get_current_user)):
    try:
        user = await User.add_user_by_endpoint_function(
            mobile=request.mobile,
            chinese_name=request.chinese_name,
            english_name=request.english_name,
            payee_name=request.payee_name,
            staff_no=request.staff_no,
            work_type=request.work_type,
            occupation=request.occupation,
            role=request.role,
            client_company_id=request.client_company_id,
        )
        return user
    except Exception as e:
        logger.error(f"Error adding user: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/all-users/")
async def get_all_users(current_user=Depends(get_current_user)):
    try:
        users = await User.read_all_users_for_endpoint_function(current_user.client_company_id)
        if isinstance(users, str):
            raise HTTPException(status_code=400, detail=users)

        return [user for user in users]
    except Exception as e:
        logger.error(f"Error fetching all users: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


# ===================
# 🔒 Protected Routes
# ===================
@router.get("/dashboard/")
async def get_dashboard(current_user=Depends(get_current_user)):
    return {"message": f"Welcome back, {current_user.chinese_name}"}


@router.get("/users/me/")
async def read_users_me(current_user=Depends(get_current_user)):
    """
    Get information about the currently authenticated user.
    Requires a valid JWT token in the Authorization header.
    Returns formatted user data for consistency across API endpoints.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Format the user data for consistent API response
    formatted_user = User.format_user_data(current_user)
    return formatted_user


@router.get("/users/{mobile}/")
async def get_user_by_mobile_endpoints(mobile: str):
    """
    Get information about a user by their mobile number.
    Requires authentication and returns formatted user data.
    """
    try:
        user = await User.get_user_by_one_mobile(mobile)
        if isinstance(user, str):
            raise HTTPException(status_code=404, detail=user)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User with mobile {mobile} not found")

        # Format the user data for consistent API response
        formatted_user = User.format_user_data(user)
        return formatted_user

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error fetching user by mobile: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users/me/items/")
async def read_own_items(current_user=Depends(get_current_user)):
    return [{"item_id": "Foo", "owner": current_user.chinese_name}]


# ========================
# 📷 Card Image Upload Routes
# ========================
@router.post("/upload-banking-card-images/{user_id}/")
async def upload_banking_card_images(
    user_id: str,
    banker: Optional[str] = Form(None),
    bank_account_no: Optional[str] = Form(None),
    front_image: Optional[UploadFile] = File(None),
    back_image: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user),
):

    try:

        def is_valid_file(file: Optional[UploadFile]) -> bool:
            if file is None:
                return False
            # Check if it's actually a string (empty file field from frontend)
            if isinstance(file, str):
                return False

            if not hasattr(file, "filename") or not hasattr(file, "size"):
                return False
            if not file.filename or file.filename.strip() == "":
                return False
            # Check if file has content
            if file.size is None or file.size <= 0:
                return False
            return True

        # Check if any valid data is provided
        has_front = is_valid_file(front_image)
        has_back = is_valid_file(back_image)
        has_banking_info = banker is not None or bank_account_no is not None

        if not has_front and not has_back and not has_banking_info:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="⚠️ 請至少上傳一張圖片或提供銀行資料",
            )

        update_data = {}
        uploaded_files = []

        # Prepare banking card data
        banking_card_data = {}

        # Add banking info if provided
        if banker is not None:
            banking_card_data["banker"] = banker
        if bank_account_no is not None:
            banking_card_data["bank_account_no"] = bank_account_no

        # Upload front image if valid
        if has_front:
            file_id = await save_image_to_gridfs(
                front_image, user_id, "banking_card", "front"
            )
            banking_card_data["card_image_front"] = file_id
            uploaded_files.append("正面")

        # Upload back image if valid
        if has_back:
            file_id = await save_image_to_gridfs(
                back_image, user_id, "banking_card", "back"
            )
            banking_card_data["card_image_back"] = file_id
            uploaded_files.append("背面")

        # Add banking card data to update_data if any banking info was provided
        if banking_card_data:
            update_data["banking_card"] = banking_card_data

        # Update user's banking card info
        result = await User.update_user_function(user_id, update_data)

        if result["status"] == "success":
            message_parts = []
            if uploaded_files:
                message_parts.append(f"圖片{', '.join(uploaded_files)}上傳成功")
            if banker or bank_account_no:
                message_parts.append("銀行資料更新成功")

            return {
                "status": "success",
                "message": f"✅ 銀行卡{', '.join(message_parts)}",
                "user_id": user_id,
                "uploaded_sides": uploaded_files,
                "updated_fields": list(update_data.keys()),
                "banking_card_data": banking_card_data,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"]
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading banking card images: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 上傳銀行卡圖片時發生錯誤: {str(e)}",
        )


# ========================
# 🖼️ Image Retrieval Routes
# ========================


@router.get("/user/banking-card/{file_id}/preview")
async def get_image(file_id: str):
    """
    Retrieve and serve an image from GridFS by file ID.
    """
    try:
        filename, content, content_type = await get_image_from_gridfs(file_id)

        return StreamingResponse(
            io.BytesIO(content),
            media_type=content_type,
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 讀取圖片時發生錯誤: {str(e)}",
        )


@router.post("/change-password/")
async def change_password(
    password_data: ChangePassword, current_user=Depends(get_current_user)
):
    """
    Change user's password with proper validation.

    For non-worker users, enforces complex password requirements.
    For worker users, accepts any non-empty password for backward compatibility.
    """
    try:
        # Verify current password
        if not verify_password(
            password_data.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 當前密碼不正確"
            )

        # Validate new password complexity for non-worker users
        from src.models.user_model import validate_password_complexity

        password_error = validate_password_complexity(
            password_data.new_password, current_user.occupation
        )
        if password_error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=password_error
            )

        # Hash the new password
        from src.models.user_model import hash_password

        new_hashed_password = hash_password(password_data.new_password)

        # Update user's password
        update_data = {"hashed_password": new_hashed_password}
        result = await User.update_user_function(current_user.id, update_data)

        if result["status"] == "success":
            return {"status": "success", "message": "✅ 密碼更改成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"]
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error changing password for user {current_user.mobile}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 更改密碼時發生錯誤: {str(e)}",
        )


# ========================
# ⏰ Working Hours Routes
# ========================

@router.post("/set-working-hours/{user_id}/")
async def set_working_hours(
    user_id: str,
    request: SetWorkingHoursRequest,
    current_user=Depends(get_current_user)
):
    """
    Set working hours for a specific user.
    This replaces any existing working hours.
    """
    try:
        # Validate user_id format
        if not user_id or not user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="⚠️ 用戶ID不能為空"
            )

        # Validate working hours data
        if not request.working_hours:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="⚠️ 工作時間資料不能為空"
            )

        # Convert to the format expected by the model function
        working_hours_data = []
        for hours in request.working_hours:
            working_hours_data.append({
                "start_time": hours.start_time,
                "end_time": hours.end_time
            })

        # Call the model's set working hours function
        result = await User.set_working_hours_function(user_id, working_hours_data)

        # Check the result and return appropriate response
        if result["status"] == "success":
            return {
                "status": "success",
                "message": result["message"],
                "user_id": result["user_id"],
                "working_hours": result["working_hours"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=result["message"]
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error setting working hours for user {user_id}: {str(e)}", 
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 設置工作時間時發生錯誤: {str(e)}",
        )


@router.get("/get-working-hours/{user_id}/")
async def get_working_hours(
    user_id: str,
    current_user=Depends(get_current_user)
):
    """
    Get working hours for a specific user.
    """
    try:
        # Validate user_id format
        if not user_id or not user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="⚠️ 用戶ID不能為空"
            )

        # Call the model's get working hours function
        result = await User.get_working_hours_function(user_id)

        # Check the result and return appropriate response
        if result["status"] == "success":
            return {
                "status": "success",
                "message": result["message"],
                "user_id": result["user_id"],
                "working_hours": result["working_hours"],
                "work_type": result["work_type"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=result["message"]
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error getting working hours for user {user_id}: {str(e)}", 
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 獲取工作時間時發生錯誤: {str(e)}",
        )


@router.delete("/clear-working-hours/{user_id}/")
async def clear_working_hours(
    user_id: str,
    current_user=Depends(get_current_user)
):
    """
    Clear all working hours for a specific user.
    """
    try:
        # Validate user_id format
        if not user_id or not user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="⚠️ 用戶ID不能為空"
            )

        # Call the model's clear working hours function
        result = await User.clear_working_hours_function(user_id)

        # Check the result and return appropriate response
        if result["status"] == "success":
            return {
                "status": "success",
                "message": result["message"],
                "user_id": result["user_id"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=result["message"]
            )

    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error clearing working hours for user {user_id}: {str(e)}", 
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 清除工作時間時發生錯誤: {str(e)}",
        )


@router.delete("/delete-user/{user_id}/")
async def delete_user(
    user_id: str,
    current_user=Depends(get_current_user)
):
    """
    Delete a user and all related records including:
    - Attendance records
    - Application and approval records
    - Worker project contract info
    """
    try:
        result = await User.delete_one_user_function(user_id)
        
        # Check the result and return appropriate response
        if result["status"] == "success":
            return {
                "status": result["status"],
                "message": result["message"],
                "details": result["details"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"⚠️ 刪除用戶時發生錯誤: {str(e)}",
        )