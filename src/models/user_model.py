import logging
import os
import re
from datetime import date, datetime, time   
from typing import List, Optional
from beanie import Document
from passlib.context import CryptContext
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from enum import Enum
from src.tools.work_permit_ocr_tool.work_permit_ocr import \
    download_image_to_memory

from src.utils.datetime_standarization_helpers import get_this_moment
from bson import ObjectId
import bcrypt

base_url = os.getenv("BASE_URL")

# Configure passlib with compatibility handling for bcrypt 4.0+
# Check bcrypt version - passlib 1.7.4 is incompatible with bcrypt 4.0+
pwd_context = None
try:
    # Try to get bcrypt version
    bcrypt_version = None
    try:
        bcrypt_version = bcrypt.__about__.__version__
    except AttributeError:
        # New way (bcrypt >= 4.0) - use importlib.metadata
        try:
            import importlib.metadata
            bcrypt_version = importlib.metadata.version('bcrypt')
        except Exception:
            bcrypt_version = getattr(bcrypt, '__version__', None)
    
    # Skip passlib if bcrypt >= 4.0
    if bcrypt_version:
        major_version = int(bcrypt_version.split('.')[0])
        if major_version >= 4:
            logging.info(f"Detected bcrypt {bcrypt_version} - passlib 1.7.4 is incompatible, using direct bcrypt")
            pwd_context = None
        else:
            # Try passlib for bcrypt < 4.0
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    else:
        # Version unknown, try passlib anyway
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    # If initialization fails, pwd_context will be None and we'll use direct bcrypt
    logging.warning(f"Passlib initialization failed in user_model: {e}, will use direct bcrypt")
    pwd_context = None

class WorkType(str, Enum):
    office_ft = "Office Full Time"
    office_pt = "Office Part Time"
    wh = "Warehouse"
    site = "Site"

class Role(str, Enum):
    director = "Director"
    supervisor = "Supervisor"
    manager = "Manager"
    worker = "worker"
    admin = "admin"
    HR = "HR"
    tech_head = "Tech Head"
    admin_head = "Admin Head"


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt. Truncates password to 72 bytes if needed.
    Falls back to direct bcrypt if passlib fails or is unavailable.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    # Convert to bytes and truncate if necessary
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        logging.warning(f"Password truncated to 72 bytes for hashing")
    
    # Use direct bcrypt if passlib is not available
    if pwd_context is None:
        try:
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password_bytes, salt)
            return hashed.decode('utf-8')
        except Exception as bcrypt_error:
            logging.error(f"Direct bcrypt hashing failed: {bcrypt_error}")
            raise ValueError(f"Password hashing failed: {bcrypt_error}")
    
    # Try passlib first
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logging.warning(f"Passlib hashing failed: {e}, falling back to direct bcrypt")
        
        # Fallback to direct bcrypt
        try:
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password_bytes, salt)
            return hashed.decode('utf-8')
        except Exception as bcrypt_error:
            logging.error(f"Direct bcrypt hashing failed: {bcrypt_error}")
            raise ValueError(f"Password hashing failed: {bcrypt_error}")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash. Truncates password to 72 bytes if needed.
    Falls back to direct bcrypt if passlib fails or is unavailable.
    """
    if not plain_password or not hashed_password:
        return False
    
    # Convert to bytes and truncate if necessary
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    # Use direct bcrypt if passlib is not available
    if pwd_context is None:
        try:
            return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
        except Exception as bcrypt_error:
            logging.error(f"Direct bcrypt verification failed: {bcrypt_error}")
            return False
    
    # Try passlib first
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logging.warning(f"Passlib verification failed: {e}, falling back to direct bcrypt")
        
        # Fallback to direct bcrypt
        try:
            return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
        except Exception as bcrypt_error:
            logging.error(f"Direct bcrypt verification failed: {bcrypt_error}")
            return False


def validate_password_complexity(password: str, occupation: str = None) -> str:

    if not password:
        raise ValueError("密碼不能為空")

    # If user is a worker, accept any non-empty password for backward compatibility
    if occupation == "worker":
        return None

    # For non-worker users, enforce complex password requirements
    if len(password) < 8:
        raise ValueError("密碼長度至少需要8個字符")

    if not re.search(r"[A-Z]", password):
        raise ValueError("密碼必須包含至少一個大寫字母")

    if not re.search(r"[a-z]", password):
        raise ValueError("密碼必須包含至少一個小寫字母")

    if not re.search(r"\d", password):
        raise ValueError("密碼必須包含至少一個數字")

    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', password):
        raise ValueError("密碼必須包含至少一個特殊字符")

    return None


class ConstructionWorkerCardInfo(BaseModel):
    card_no: str
    issue_date: date
    expiry_date: date
    card_image_front: str
    card_image_back: Optional[str] = None


class CertifiedWorkerCardInfo(BaseModel):
    reference_no: str
    issue_date: date
    expiry_date: date
    card_image_front: str
    card_image_back: Optional[str] = None

    @computed_field
    @property
    def user_id(self) -> str:
        return str(self.id)

    @computed_field
    @property
    def certified_worker_card_front_url(self) -> Optional[str]:
        if not self.card_image_front:
            return None
        return f"{base_url}/user/certified-worker-card/{self.user_id}/{self.card_image_front}/preview"

    @computed_field
    @property
    def certified_worker_card_back_url(self) -> Optional[str]:
        if not self.card_image_back:
            return None
        return f"{base_url}/user/certified-worker-card/{self.user_id}/{self.card_image_back}/preview"


class NationalIDInfo(BaseModel):
    card_image_front: str
    card_image_back: Optional[str] = None


class BankingCardInfo(BaseModel):
    banker: Optional[str] = None
    bank_account_no: Optional[str] = None
    card_image_front: Optional[str] = None
    card_image_back: Optional[str] = None

    @computed_field
    @property
    def card_image_front_url(self) -> Optional[str]:
        if not self.card_image_front:
            return None
        return f"{base_url}/user/banking-card/{self.card_image_front}/preview"

    @computed_field
    @property
    def card_image_back_url(self) -> Optional[str]:
        if not self.card_image_back:
            return None
        return f"{base_url}/user/banking-card/{self.card_image_back}/preview"


class AdditionalCardInfo(BaseModel):
    card_name: str
    card_no: str
    issue_date: date
    expiry_date: date
    card_image_front: str
    card_image_back: Optional[str] = None

    @computed_field
    @property
    def additional_card_front_url(self) -> Optional[str]:
        if not self.card_image_front:
            return None
        return f"{base_url}/user/additional-card/{self.card_image_front}/preview"

    @computed_field
    @property
    def additional_card_back_url(self) -> Optional[str]:
        if not self.card_image_back:
            return None
        return f"{base_url}/user/additional-card/{self.card_image_back}/preview"



class WorkingHours(BaseModel):
    start_time: str  # Store as string in format "HH:MM"
    end_time: str    # Store as string in format "HH:MM"

# Default working hours mapping for each work type
DEFAULT_WORKING_HOURS = {
    WorkType.office_ft: [WorkingHours(start_time="09:00", end_time="18:00")],
    WorkType.office_pt: None,  # Part-time workers have flexible hours
    WorkType.wh: [WorkingHours(start_time="08:00", end_time="18:00")],  # Warehouse typically starts earlier
    WorkType.site: [WorkingHours(start_time="08:00", end_time="18:00")],  # Construction sites start early
    WorkType.office_ft and Role.manager: None,  # Manager has flexible hours
    WorkType.office_ft and Role.director: None,  # Manager has flexible hours
}

class User(Document):
    client_company_id: str
    country_code: str
    mobile: List[str]
    payee_name: str
    staff_no: str
    occupation: str
    work_type: WorkType
    working_hours: Optional[List[WorkingHours]] = None 
    approved_by: Optional[List[str]] = None

    role: Optional[List[Role]] = None #manager roles 
    gender: Optional[str] = None
    dob: Optional[date] = None
    national_id_no: Optional[str] = None
    english_name: Optional[str] = None
    chinese_name: Optional[str] = None
    address: Optional[str] = None
    bonus_desc: Optional[str] = None  # include bonus description and bonus amount
    over_65: bool = False  # age over 65

    hashed_password: Optional[str] = None
    banking_card: Optional[BankingCardInfo] = None
    national_id_card: Optional[NationalIDInfo] = None
    construction_worker_card: Optional[ConstructionWorkerCardInfo] = None
    certified_worker_card: Optional[CertifiedWorkerCardInfo] = None
    additional_cards: Optional[List[AdditionalCardInfo]] = None

    cards_unprocessed: Optional[List[str]] = None

    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    is_active: bool = True

    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "user_collection"

    class Config:
        arbitrary_types_allowed = True

    @computed_field
    @property
    def user_id(self) -> str:
        return str(self.id)


    @field_validator('work_type', mode='before')
    @classmethod
    def validate_work_type(cls, v):
        """Convert string to WorkType enum"""
        if v is None:
            return None
        if isinstance(v, WorkType):
            return v
        if isinstance(v, str):
            # Try to find matching WorkType by value
            for work_type in WorkType:
                if work_type.value == v:
                    return work_type
            # If no exact match, try case-insensitive match
            for work_type in WorkType:
                if work_type.value.lower() == v.lower():
                    return work_type
            # If still no match, raise an error
            raise ValueError(f"Invalid work_type: {v}. Must be one of: {[wt.value for wt in WorkType]}")
        return v

    @field_validator('working_hours', mode='before')
    @classmethod
    def validate_working_hours_format(cls, v):
        """Convert list of dicts to list of WorkingHours objects"""
        if v is None:
            return None
        if isinstance(v, list):
            # Convert list of dicts to list of WorkingHours objects
            working_hours_list = []
            for item in v:
                if isinstance(item, dict):
                    working_hours_list.append(WorkingHours(**item))
                elif isinstance(item, WorkingHours):
                    working_hours_list.append(item)
            return working_hours_list
        elif isinstance(v, WorkingHours):
            return [v]
        return v

    @model_validator(mode='after')
    def validate_working_hours(self):
        """Set default working hours based on work type if not provided"""
        if self.working_hours is None and self.work_type in DEFAULT_WORKING_HOURS:
            self.working_hours = DEFAULT_WORKING_HOURS[self.work_type]
        return self

    def get_working_hours_for_work_type(self, work_type: WorkType) -> Optional[List[WorkingHours]]:
        """Get default working hours for a specific work type"""
        return DEFAULT_WORKING_HOURS.get(work_type)

    def set_working_hours_for_work_type(self, work_type: WorkType, working_hours: Optional[List[WorkingHours]]):
        """Set working hours for a specific work type"""
        if self.work_type == work_type:
            self.working_hours = working_hours


    @computed_field
    @property
    def needs_password_change(self) -> bool:

        if self.role and "worker" in self.role:
            return False

        # Check if password is a temporary one or matches common default patterns
        if hasattr(self, "hashed_password") and self.hashed_password:
            # This is a simple heuristic - in practice, you might want to track
            # which users have temporary passwords more explicitly
            return True  # For now, assume all non-workers need password change

        return False

    @computed_field
    @property
    def national_id_card_front_url(self) -> Optional[str]:
        if not self.national_id_card or not self.national_id_card.card_image_front:
            return None
        return f"{base_url}/user/national-id-card/{self.user_id}/front"

    @computed_field
    @property
    def national_id_card_back_url(self) -> Optional[str]:
        if not self.national_id_card or not self.national_id_card.card_image_back:
            return None
        return f"{base_url}/user/national-id-card/{self.user_id}/back"

    @classmethod
    async def alternative_registration_function(
        cls,
        occupation,
        card_name,
        english_name,
        chinese_name,
        national_id_no,
        dob,
        gender,
        country_code,
        mobile,
        national_id_image,
    ):
        try:
            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            existing_user = await cls.find_one(
                cls.mobile == mobile, cls.deleted_at == None
            )
            if existing_user:
                raise ValueError(f"⚠️ 呢個手機號碼為{mobile}嘅用戶已添加。")

            if (
                isinstance(dob, str)
                and len(dob) == 10
                and dob[2] == "-"
                and dob[5] == "-"
            ):
                day, month, year = dob.split("-")
                dob = f"{year}-{month}-{day}"

            new_user = cls(
                occupation=occupation,
                card_name=card_name,
                english_name=english_name,
                chinese_name=chinese_name,
                national_id_no=national_id_no,
                dob=dob,
                gender=gender,
                country_code=country_code,
                mobile=mobile_list,
                national_id_card=NationalIDInfo(card_image_front=national_id_image),
                created_at=get_this_moment(),
            )
            await new_user.insert()

            return {"status": "success", "message": f"用戶{chinese_name}已成功添加。"}
        except Exception as e:
            logging.error(f"Error processing alternative registration: {str(e)}")
            return {"status": "error", "message": str(e)}


    @classmethod
    async def _find_approvers(cls, user_id: str) -> List[str]:
        """Find the approvers for the application"""
        try:
            user_info = await cls.find_one(cls.id == ObjectId(user_id), cls.deleted_at == None)
            if not user_info:
                return []
            return user_info.approved_by
        except Exception as e:
            logging.error(f"Failed to find approvers for user: {str(e)}")
            return []


    @classmethod
    async def add_user_by_endpoint_function(
        cls,
        mobile: List[str],
        payee_name: str,
        staff_no: str,
        work_type: WorkType,
        occupation: str,
        client_company_id: str,
        chinese_name: Optional[str] = None,
        english_name: Optional[str] = None,
        role: Optional[List[str]] = None,
    ):
        """Add a new user with comprehensive error handling."""
        try:
            # Input validation
            if not mobile or len(mobile) == 0:
                raise ValueError("⚠️ 手機號碼不能為空。")

            if not payee_name or not payee_name.strip():
                raise ValueError("⚠️ 收款人名稱不能為空。")

            if not staff_no or not staff_no.strip():
                raise ValueError("⚠️ 員工編號不能為空。")

            if not work_type:
                raise ValueError("⚠️ 工作類型不能為空。")

            if not occupation or not occupation.strip():
                raise ValueError("⚠️ 職業不能為空。")

            # Validate that at least one name is provided
            if not chinese_name and not english_name:
                raise ValueError("⚠️ 必須提供中文名或英文名。")

            # Sanitize inputs - ensure mobile is a list
            mobile_list = mobile if isinstance(mobile, list) else [str(mobile).strip()]
            payee_name = str(payee_name).strip()
            staff_no = str(staff_no).strip()
            occupation = str(occupation).strip()
            chinese_name = str(chinese_name).strip() if chinese_name else None
            english_name = str(english_name).strip() if english_name else None

            # Check for existing user
            try:
                existing_user = await cls.find_one(
                    cls.mobile == mobile, cls.deleted_at == None
                )
                if existing_user:
                    raise ValueError(f"⚠️ 呢個手機號碼為{mobile_list}嘅用戶已添加。")
            except ValueError:
                # Re-raise ValueError for duplicate user
                raise
            except Exception as db_error:
                logging.error(f"Database error checking existing user: {str(db_error)}")
                raise ValueError("⚠️ 檢查用戶時發生數據庫錯誤。")

            # Hash password - use first mobile number for password
            try:
                default_password = mobile_list[0]
                hashed_password = hash_password(default_password)
            except Exception as hash_error:
                logging.error(f"Password hashing error: {str(hash_error)}")
                raise ValueError("⚠️ 密碼加密失敗。")

            # Create new user
            country_code = "852"
            try:
                new_user = cls(
                    client_company_id=client_company_id,
                    country_code=str(country_code),
                    mobile=mobile_list,
                    payee_name=payee_name,
                    staff_no=staff_no,
                    work_type=work_type,
                    role=role if role and len(role) > 0 else ["worker"],
                    occupation=occupation,
                    chinese_name=chinese_name,
                    english_name=english_name,
                    hashed_password=hashed_password,
                    created_at=get_this_moment(),
                )
            except Exception as create_error:
                logging.error(f"Error creating user object: {str(create_error)}")
                raise ValueError("⚠️ 創建用戶對象失敗。")

            # Insert user into database
            try:
                await new_user.insert()
            except Exception as insert_error:
                logging.error(f"Database insertion error: {str(insert_error)}")
                raise ValueError("⚠️ 保存用戶到數據庫失敗。")

            # Determine display name
            name = chinese_name if chinese_name else english_name

            logging.info(f"Successfully added user: {name} (mobile: {mobile_list})")

            return {
                "status": "success",
                "message": f"用戶{name}已成功添加。",
                "user_id": str(new_user.id) if hasattr(new_user, "id") else None,
            }

        except ValueError as ve:
            # Known validation errors
            logging.warning(f"Validation error in add_user_by_endpoint: {str(ve)}")
            return {"status": "error", "message": str(ve)}
        except Exception as e:
            # Unexpected errors
            logging.error(
                f"Unexpected error in add_user_by_endpoint: {str(e)}", exc_info=True
            )
            return {
                "status": "error",
                "message": "⚠️ 添加用戶時發生意外錯誤，請聯繫系統管理員。",
            }


    @classmethod
    async def get_user_by_one_mobile(cls, one_mobile: str):
        """
        Get information about a user by their mobile number. 
        mobile is a list of strings.
        """
        # Since mobile is a list field, we need to check if one_mobile is in that list
        user = await cls.find_one(
            cls.mobile == one_mobile,  # This checks if one_mobile exists in the mobile list
            cls.deleted_at == None
        )
        return user


    @classmethod
    async def get_user_approvers(cls, user_id: str):
        """Get the approvers for the application
        result is a list of dictionaries, each dictionary contains the approver's name and waba(approver_name, approver_waba)
        user_info.approved_by is a list of ObjectId
        """
        try:
            user_info = await cls.find_one(cls.id == ObjectId(user_id), cls.deleted_at == None)
            if not user_info or not user_info.approved_by:
                return []

            approver_ids = []
            for approver_id in user_info.approved_by:
                try:
                    approver_ids.append(ObjectId(approver_id))
                except Exception:
                    logging.warning(f"Invalid approver id '{approver_id}' for user '{user_id}'")

            if not approver_ids:
                return []

            result = []
            for approver_id in approver_ids:
                approver = await cls.find_one(cls.id == ObjectId(approver_id), cls.deleted_at == None)
                if not approver or not approver.mobile:
                    continue

                approver_name = approver.payee_name
                approver_mobile = approver.mobile[0] if approver.mobile else None
                if not approver_mobile:
                    continue

                result.append(
                    {
                        "approver_name": approver_name,
                        "approver_waba": f"whatsapp:+852{approver_mobile}",
                    }
                )

            return result
        except Exception as e:
            logging.error(f"Failed to find approvers for user: {str(e)}")
            return []


    @classmethod
    async def read_all_users_for_endpoint_function(cls, client_company_id: str):
        try:
            all_users_info = await cls.find(cls.client_company_id == client_company_id, cls.deleted_at == None).to_list()
            all_users_info = [
                {
                    "user_id": user.user_id,
                    "country_code": user.country_code,
                    "mobile": user.mobile,
                    "payee_name": user.payee_name,
                    "staff_no": user.staff_no,
                    "work_type": user.work_type,
                    "occupation": user.occupation,
                    "role": user.role if user.role else None,
                    "english_name": user.english_name if user.english_name else None,
                    "chinese_name": user.chinese_name if user.chinese_name else None,
                    "dob": user.dob.isoformat() if user.dob else None,
                    "national_id_no": (
                        user.national_id_no if user.national_id_no else None
                    ),
                    "address": user.address if user.address else None,
                    "over_65": user.over_65 if user.over_65 else None,
                    "is_active": user.is_active,
                    "banking_card": (
                        {
                            "banker": user.banking_card.banker,
                            "bank_account_no": user.banking_card.bank_account_no,
                            "card_image_front_url": user.banking_card.card_image_front_url,
                            "card_image_back_url": user.banking_card.card_image_back_url,
                        }
                        if user.banking_card
                        else None
                    ),
                    "national_id_card": (
                        {
                            "card_image_front_url": user.national_id_card_front_url,
                            "card_image_back_url": user.national_id_card_back_url,
                        }
                        if user.national_id_card
                        else None
                    ),
                    "construction_worker_card": (
                        {
                            "card_no": user.construction_worker_card.card_no,
                            "issue_date": (
                                user.construction_worker_card.issue_date.isoformat()
                                if user.construction_worker_card.issue_date
                                else None
                            ),
                            "expiry_date": (
                                user.construction_worker_card.expiry_date.isoformat()
                                if user.construction_worker_card.expiry_date
                                else None
                            ),
                        }
                        if user.construction_worker_card
                        else None
                    ),
                    "certified_worker_card": (
                        {
                            "reference_no": user.certified_worker_card.reference_no,
                            "issue_date": (
                                user.certified_worker_card.issue_date.isoformat()
                                if user.certified_worker_card.issue_date
                                else None
                            ),
                            "expiry_date": (
                                user.certified_worker_card.expiry_date.isoformat()
                                if user.certified_worker_card.expiry_date
                                else None
                            ),
                            "card_image_front_url": user.certified_worker_card.certified_worker_card_front_url,
                            "card_image_back_url": user.certified_worker_card.certified_worker_card_back_url,
                        }
                        if user.certified_worker_card
                        else None
                    ),
                    "additional_cards": (
                        [
                            {
                                "card_name": card.card_name,
                                "card_no": card.card_no,
                                "issue_date": (
                                    card.issue_date.isoformat()
                                    if card.issue_date
                                    else None
                                ),
                                "expiry_date": (
                                    card.expiry_date.isoformat()
                                    if card.expiry_date
                                    else None
                                ),
                                "card_image_front_url": card.additional_card_front_url,
                                "card_image_back_url": card.additional_card_back_url,
                            }
                            for card in user.additional_cards
                        ]
                        if user.additional_cards
                        else None
                    ),
                    "emergency_contact_name": (
                        user.emergency_contact_name
                        if user.emergency_contact_name
                        else None
                    ),
                    "emergency_contact_phone": (
                        user.emergency_contact_phone
                        if user.emergency_contact_phone
                        else None
                    ),
                }
                for user in all_users_info
            ]

            logging.info(
                f"all_users_info in read_all_users_for_endpoint_function: {len(all_users_info)} users found"
            )
            return all_users_info
        except Exception as e:
            logging.error(f"Error fetching all users data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def add_user_by_chatbot_function(
        cls,
        country_code: str,
        mobile: List[str],
        english_name: str,
        chinese_name: str,
        gender: str,
        dob: date,
        national_id_no: str,
        password: str,
        address: Optional[str] = None,
        occupation: Optional[str] = None,
        national_id_card: Optional[dict] = None,
    ):
        try:

            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            existing_user = await cls.find_one(
                cls.mobile == mobile, cls.deleted_at == None
            )

            if existing_user:
                raise ValueError(f"⚠️ 呢啲手機號碼為{mobile_list}嘅用戶已添加。")

            # Validate password complexity for non-worker users
            password_error = validate_password_complexity(password, occupation)
            if password_error:
                raise ValueError(password_error)

            hashed_password = hash_password(password)

            age = get_this_moment().year - dob.year
            if age >= 65:
                over_65 = True
            else:
                over_65 = False

            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            new_user = cls(
                country_code=country_code,
                mobile=mobile_list,
                english_name=english_name,
                chinese_name=chinese_name,
                gender=gender,
                dob=dob,
                national_id_no=national_id_no,
                occupation=occupation,
                address=address,
                over_65=over_65,
                hashed_password=hashed_password,
                national_id_card=(
                    NationalIDInfo(**national_id_card) if national_id_card else None
                ),
                created_at=get_this_moment(),
            )

            await new_user.insert()

            message = f"🎉 Welcome, {chinese_name}! 成功加咗你啦～依家可以開始打卡喇！\n\n不過要留意呀～每日最多打三次: 朝早簽到，放工簽退～ 再打多次都冇用㗎，只係睇到你今日打卡嘅時間啫～ 🙌"

            return {"status": "success", "message": message, "new_user": new_user}

        except Exception as e:
            logging.error(f"Error adding user: {str(e)}")
            return {"status": "error", "message": str(e)}

    @classmethod
    async def get_user_id_by_mobile(cls, country_code: str, mobile: List[str]):
        # Convert mobile to list if it's a string
        mobile_list = [mobile] if isinstance(mobile, str) else mobile
        
        worker_info = await cls.find_one(
            cls.country_code == country_code,
            cls.mobile == mobile,
            cls.deleted_at == None,
        )
        if worker_info:
            worker_id = str(worker_info.id)
            return worker_id
        return None

    @classmethod
    async def read_all_workers_by_director_function(cls):
        try:
            all_workers_info = await cls.find(cls.deleted_at == None).to_list()

            all_workers_info = [
                {
                    "payee_name": worker.payee_name,
                    "staff_no": worker.staff_no,
                    "work_type": worker.work_type,
                    "occupation": worker.occupation,
                    "role": worker.role if worker.role else None,
                    "english_name": (
                        worker.english_name if worker.english_name else None
                    ),
                    "chinese_name": (
                        worker.chinese_name if worker.chinese_name else None
                    ),
                    "mobile": worker.mobile,
                }
                for worker in all_workers_info
            ]

            return all_workers_info

        except Exception as e:
            logging.error(f"Error fetching all workers data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def user_register_function(
        cls,
        user_waba: str,
        name: str,
        occupation: str,
        work_type: WorkType,
        staff_no: str,
        payee_name: str,
        address: Optional[str] = None,
    ):
        try:
            from src.utils.standardization_helpers import \
                normalize_mobile_from_whatsapp

            mobile_info = normalize_mobile_from_whatsapp(user_waba)
            country_code = mobile_info["country_code"]
            mobile = mobile_info["mobile_digits"]
            role = ["worker"]

            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            user_info = await cls.find_one(
                cls.country_code == country_code,
                cls.mobile == mobile,
                cls.deleted_at == None,
            )
            if user_info:
                raise ValueError(f"⚠️ 呢個手機號碼為{mobile_list}嘅用戶已經註冊。")

            default_password = mobile_list[0]
            hashed_password = hash_password(default_password)

            new_user = cls(
                country_code=country_code,
                mobile=mobile_list,
                payee_name=payee_name,
                staff_no=staff_no,
                work_type=work_type,
                role=role,
                occupation=occupation,
                chinese_name=name,
                address=address,
                hashed_password=hashed_password,
                created_at=get_this_moment(),
            )
            await new_user.insert()

            message = f"🎉 用戶{name}已成功註冊。"

            return {"status": "success", "message": message, "new_user": new_user}

        except Exception as e:
            logging.error(f"Error user register: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def read_all_user_function(cls):
        try:
            all_users_info = await cls.find(cls.deleted_at == None).to_list()

            user_data = [
                {
                    "name": (
                        user.english_name if user.english_name else user.chinese_name
                    ),
                    "mobile": user.mobile,
                    "occupation": user.occupation,
                    "address": user.address,
                    "over_65": user.over_65,
                    "banking_card": user.banking_card,
                    "national_id_card": user.national_id_card,
                    "construction_worker_card": user.construction_worker_card,
                    "certified_worker_card": user.certified_worker_card,
                }
                for user in all_users_info
            ]

            return user_data

        except Exception as e:
            logging.error(f"Error fetching user data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def read_a_user(cls, mobile: List[str]):
        """
        Fetch a user by mobile number and return the user document.
        This method is used for authentication and should return the raw user document.

        Args:
            mobile (List[str]): The mobile number(s) to search for

        Returns:
            User: The user document if found
            None: If no user is found
            str: Error message if an exception occurs
        """
        try:
            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            # First check if the user exists
            user = await cls.find_one(cls.mobile == mobile, cls.deleted_at == None)
            logging.info(f"User with mobile {mobile_list} found: {user}")

            if not user:
                logging.warning(f"User with mobile {mobile_list} not found")
                return None

            return user

        except Exception as e:
            logging.error(f"Error fetching user data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def get_user_by_mobile(cls, mobile: List[str]):
        """
        Fetch a user by mobile number and return the user document.
        Similar to read_a_user but with different error handling.

        Args:
            mobile (List[str]): The mobile number(s) to search for

        Returns:
            User: The user document if found
            None: If no user is found
            str: Error message if an exception occurs
        """
        try:
            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            user = await cls.find_one(cls.mobile == mobile, cls.deleted_at == None)
            logging.info(f"User with mobile {mobile_list} found: {user}")
            return user
        except Exception as e:
            logging.error(f"Error fetching user data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    def format_user_data(cls, user):

        if not user:
            return None

        try:
            # Helper function to safely get attribute
            def safe_get(obj, attr, default=None):
                return getattr(obj, attr, default) if obj else default

            # Helper function to safely format date
            def safe_date(date_obj):
                return date_obj.isoformat() if date_obj else None

            # Helper function to safely convert to string
            def safe_str(value, default=None):
                return str(value) if value is not None else default

            return {
                # Basic user information
                "user_id": safe_str(user.id),
                "country_code": safe_str(user.country_code),
                "mobile": user.mobile if isinstance(user.mobile, list) else [user.mobile] if user.mobile else [],
                "english_name": safe_str(user.english_name),
                "chinese_name": safe_str(user.chinese_name),
                "gender": safe_str(user.gender),
                "dob": safe_date(safe_get(user, "dob")),
                "national_id_no": safe_str(user.national_id_no),
                "occupation": safe_get(user, "occupation"),
                "address": safe_get(user, "address"),
                "bonus_desc": safe_get(user, "bonus_desc"),
                "over_65": safe_get(user, "over_65", False),
                "is_active": safe_get(user, "is_active", True),
                "needs_password_change": safe_get(user, "needs_password_change", False),
                "created_at": safe_date(safe_get(user, "created_at")),
                "deleted_at": safe_date(safe_get(user, "deleted_at")),
                # Banking card information with computed URLs
                "banking_card": cls._format_banking_card(
                    safe_get(user, "banking_card")
                ),
                # National ID card information with computed URLs
                "national_id_card": cls._format_national_id_card(user),
                # Construction worker card information
                "construction_worker_card": cls._format_construction_worker_card(
                    safe_get(user, "construction_worker_card")
                ),
                # Certified worker card information with computed URLs
                "certified_worker_card": cls._format_certified_worker_card(
                    safe_get(user, "certified_worker_card")
                ),
                # Additional cards information with computed URLs
                "additional_cards": cls._format_additional_cards(
                    safe_get(user, "additional_cards")
                ),
                # Worker projects information with computed URLs and hourly rate
                "worker_projects": cls._format_worker_projects(
                    safe_get(user, "worker_projects")
                ),
                # Emergency contact information
                "emergency_contact_name": safe_get(user, "emergency_contact_name"),
                "emergency_contact_phone": safe_get(user, "emergency_contact_phone"),
            }
        except Exception as e:
            logging.error(f"Error formatting user data: {str(e)}")
            # Return a minimal set of user data in case of error
            return {
                "user_id": str(user.id) if hasattr(user, "id") else None,
                "mobile": getattr(user, "mobile", []) if isinstance(getattr(user, "mobile", None), list) else [getattr(user, "mobile", None)] if getattr(user, "mobile", None) else [],
                "chinese_name": getattr(user, "chinese_name", None),
                "english_name": getattr(user, "english_name", None),
                "error": f"Error formatting complete user data: {str(e)}",
            }

    @classmethod
    def _format_banking_card(cls, banking_card):
        """Format banking card data safely."""
        if not banking_card:
            return None

        return {
            "banker": getattr(banking_card, "banker", None),
            "bank_account_no": getattr(banking_card, "bank_account_no", None),
            "card_image_front_url": getattr(banking_card, "card_image_front_url", None),
            "card_image_back_url": getattr(banking_card, "card_image_back_url", None),
        }

    @classmethod
    def _format_national_id_card(cls, user):
        """Format national ID card data safely."""
        if not hasattr(user, "national_id_card") or not user.national_id_card:
            return None

        return {
            "card_image_front_url": getattr(user, "national_id_card_front_url", None),
            "card_image_back_url": getattr(user, "national_id_card_back_url", None),
        }

    @classmethod
    def _format_construction_worker_card(cls, card):
        """Format construction worker card data safely."""
        if not card:
            return None

        return {
            "card_no": getattr(card, "card_no", None),
            "issue_date": (
                card.issue_date.isoformat()
                if hasattr(card, "issue_date") and card.issue_date
                else None
            ),
            "expiry_date": (
                card.expiry_date.isoformat()
                if hasattr(card, "expiry_date") and card.expiry_date
                else None
            ),
        }

    @classmethod
    def _format_certified_worker_card(cls, card):
        """Format certified worker card data safely."""
        if not card:
            return None

        return {
            "reference_no": getattr(card, "reference_no", None),
            "issue_date": (
                card.issue_date.isoformat()
                if hasattr(card, "issue_date") and card.issue_date
                else None
            ),
            "expiry_date": (
                card.expiry_date.isoformat()
                if hasattr(card, "expiry_date") and card.expiry_date
                else None
            ),
            "card_image_front_url": getattr(
                card, "certified_worker_card_front_url", None
            ),
            "card_image_back_url": getattr(
                card, "certified_worker_card_back_url", None
            ),
        }

    @classmethod
    def _format_additional_cards(cls, cards):
        """Format additional cards data safely."""
        if not cards:
            return None

        # Ensure cards is iterable
        if not hasattr(cards, "__iter__"):
            logging.warning(f"additional_cards is not iterable: {type(cards)}")
            return None

        try:
            formatted_cards = []
            for card in cards:
                if card:  # Skip None entries
                    formatted_cards.append(
                        {
                            "card_name": getattr(card, "card_name", None),
                            "card_no": getattr(card, "card_no", None),
                            "issue_date": (
                                card.issue_date.isoformat()
                                if hasattr(card, "issue_date") and card.issue_date
                                else None
                            ),
                            "expiry_date": (
                                card.expiry_date.isoformat()
                                if hasattr(card, "expiry_date") and card.expiry_date
                                else None
                            ),
                            "card_image_front_url": getattr(
                                card, "additional_card_front_url", None
                            ),
                            "card_image_back_url": getattr(
                                card, "additional_card_back_url", None
                            ),
                        }
                    )
            return formatted_cards if formatted_cards else None
        except TypeError as e:
            logging.error(f"Error iterating over additional_cards: {str(e)}")
            return None

    @classmethod
    def _format_worker_projects(cls, projects):
        """Format worker projects data safely."""
        if not projects:
            return None

        # Ensure projects is iterable
        if not hasattr(projects, "__iter__"):
            logging.warning(f"worker_projects is not iterable: {type(projects)}")
            return None

        try:
            formatted_projects = []
            for project in projects:
                if project:  # Skip None entries
                    formatted_projects.append(
                        {
                            "contract_document_id": getattr(
                                project, "contract_document_id", None
                            ),
                            "is_daily_contract": getattr(
                                project, "is_daily_contract", True
                            ),
                            "salary": getattr(project, "salary", None),
                            "hourly_rate": (
                                str(project.hourly_rate)
                                if hasattr(project, "hourly_rate")
                                and project.hourly_rate
                                else None
                            ),
                            "contract_no": getattr(project, "contract_no", None),
                            "position": getattr(project, "position", None),
                            "contract_issue_date": (
                                project.contract_issue_date.isoformat()
                                if hasattr(project, "contract_issue_date")
                                and project.contract_issue_date
                                else None
                            ),
                            "contract_start_date": (
                                project.contract_start_date.isoformat()
                                if hasattr(project, "contract_start_date")
                                and project.contract_start_date
                                else None
                            ),
                            "probation_period": getattr(
                                project, "probation_period", None
                            ),
                            "bonus": getattr(project, "bonus", None),
                            "contract_download_url": getattr(
                                project, "contract_download_url", None
                            ),
                        }
                    )
            return formatted_projects if formatted_projects else None
        except TypeError as e:
            logging.error(f"Error iterating over worker_projects: {str(e)}")
            return None


    @classmethod
    async def update_user_function(cls, user_id: str, update_data: dict):

        try:

            if not user_id or not update_data:
                return {"status": "error", "message": "⚠️ 用戶ID和更新資料不能為空"}

            try:
                object_id = ObjectId(user_id)
            except Exception:
                return {"status": "error", "message": f"⚠️ 無效的用戶ID格式: {user_id}"}

            # Find the user
            user = await cls.find_one(cls.id == object_id, cls.deleted_at == None)
            if not user:
                return {
                    "status": "error",
                    "message": f"⚠️ 找不到工人資料，工人ID: {user_id}",
                }

            logging.info(
                f"Updating user {user_id} with fields: {list(update_data.keys())}"
            )

            # Helper function to update card information
            def update_card_info(card_field, card_data, card_class):
                if isinstance(card_data, dict):
                    existing_card = getattr(user, card_field)
                    if existing_card:
                        # Use model_dump() for Pydantic v2 compatibility
                        existing_dict = existing_card.model_dump()
                        for key, value in card_data.items():
                            if value is not None:
                                existing_dict[key] = value
                        setattr(user, card_field, card_class(**existing_dict))
                    else:
                        setattr(user, card_field, card_class(**card_data))
                else:
                    setattr(user, card_field, card_data)
                return True

            # Handle special card updates
            card_updates = {
                "banking_card": BankingCardInfo,
                "national_id_card": NationalIDInfo,
                "construction_worker_card": ConstructionWorkerCardInfo,
                "certified_worker_card": CertifiedWorkerCardInfo,
            }

            for card_field, card_class in card_updates.items():
                if card_field in update_data and update_data[card_field] is not None:
                    update_card_info(card_field, update_data[card_field], card_class)
                    del update_data[card_field]

            # Handle date fields
            date_fields = ["dob", "created_at", "deleted_at"]
            for field in date_fields:
                if field in update_data and update_data[field] is not None:
                    try:
                        if isinstance(update_data[field], str):
                            if field == "dob":
                                update_data[field] = date.fromisoformat(
                                    update_data[field]
                                )
                            else:
                                update_data[field] = datetime.fromisoformat(
                                    update_data[field]
                                )
                    except ValueError as e:
                        logging.error(
                            f"Invalid date format for {field}: {update_data[field]}"
                        )
                        return {
                            "status": "error",
                            "message": f"⚠️ 日期格式錯誤 ({field}): {str(e)}",
                        }

            # Handle additional_cards list
            if (
                "additional_cards" in update_data
                and update_data["additional_cards"] is not None
            ):
                try:
                    cards_data = update_data["additional_cards"]
                    if isinstance(cards_data, list):
                        additional_cards = []
                        for card_data in cards_data:
                            additional_cards.append(AdditionalCardInfo(**card_data))
                        user.additional_cards = additional_cards
                    del update_data["additional_cards"]
                except Exception as e:
                    logging.error(f"Error updating additional cards: {str(e)}")
                    return {
                        "status": "error",
                        "message": f"⚠️ 更新附加卡資料錯誤: {str(e)}",
                    }

            # Handle other simple field updates
            for field, value in update_data.items():
                if hasattr(user, field) and value is not None:
                    setattr(user, field, value)
                else:
                    logging.warning(f"Skipping unknown field: {field}")

            # Save the updated user
            await user.save()

            logging.info(f"Successfully updated user {user_id}")
            return {
                "status": "success",
                "message": f"✅ 工人資料更新成功",
                "user_id": str(user.id),
            }

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error updating user {user_id}: {error_msg}", exc_info=True)

            if "duplicate key" in error_msg.lower():
                return {"status": "error", "message": "⚠️ 資料更新失敗: 有重複的資料"}
            elif "validation" in error_msg.lower():
                return {"status": "error", "message": f"⚠️ 資料驗證失敗: {error_msg}"}
            else:
                return {"status": "error", "message": f"⚠️ 發生錯誤: {error_msg}"}


    @classmethod
    async def add_user_card_function(
        cls,
        card_type: str,
        card_holder_name: str,
        card_no: str,
        card_issue_date: date,
        card_expiry_date: date,
        card_image: str,
    ):
        try:
            import base64

            from src.tools.work_permit_ocr_tool.work_permit_ocr import \
                download_image_to_memory

            existing_user = await cls.find_one(
                cls.chinese_name == card_holder_name, cls.deleted_at == None
            )

            image_bytes = await download_image_to_memory(card_image)
            card_image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            if existing_user:
                if "Registration Card" in card_type or "註冊" in card_type:
                    existing_user.created_at = get_this_moment()
                    existing_user.construction_worker_card = ConstructionWorkerCardInfo(
                        registration_no=card_no,
                        issue_date=card_issue_date,
                        expiry_date=card_expiry_date,
                        card_image_front=card_image_base64,
                    )

                elif (
                    "Safety Training Certificate" in card_type
                    or "安全"
                    or "certified"
                    or "certificate" in card_type
                ):
                    existing_user.created_at = get_this_moment()
                    existing_user.certified_worker_card = CertifiedWorkerCardInfo(
                        reference_no=card_no,
                        issue_date=card_issue_date,
                        expiry_date=card_expiry_date,
                        card_image_front=card_image_base64,
                    )

                else:
                    # Default to construction worker card if type is unclear
                    logging.warning(
                        f"Unknown card type: {card_type}, defaulting to construction worker card"
                    )
                    existing_user.created_at = get_this_moment()
                    existing_user.certified_worker_card = CertifiedWorkerCardInfo(
                        reference_no=card_no,
                        issue_date=card_issue_date,
                        expiry_date=card_expiry_date,
                        card_image_front=card_image_base64,
                    )

                await existing_user.save()
                return existing_user
            else:
                # Create new worker with construction card
                if "Registration Card" in card_type or "註冊" in card_type:
                    new_user = cls(
                        name=card_holder_name,
                        created_at=get_this_moment(),
                        construction_worker_card=ConstructionWorkerCardInfo(
                            registration_no=card_no,
                            issue_date=card_issue_date,
                            expiry_date=card_expiry_date,
                            card_image_front=card_image_base64,
                        ),
                    )
                elif (
                    "Safety Training Certificate" in card_type
                    or "安全"
                    or "certified"
                    or "certificate" in card_type
                ):
                    new_user = cls(
                        name=card_holder_name,
                        created_at=get_this_moment(),
                        certified_worker_card=CertifiedWorkerCardInfo(
                            reference_no=card_no,
                            issue_date=card_issue_date,
                            expiry_date=card_expiry_date,
                            card_image_front=card_image_base64,
                        ),
                    )
                else:
                    # Default to construction worker card if type is unclear
                    logging.warning(
                        f"Unknown card type: {card_type}, defaulting to construction worker card"
                    )
                    new_user = cls(
                        name=card_holder_name,
                        created_at=get_this_moment(),
                        construction_worker_card=ConstructionWorkerCardInfo(
                            registration_no=card_no,
                            issue_date=card_issue_date,
                            expiry_date=card_expiry_date,
                            card_image_front=card_image_base64,
                        ),
                    )

                await new_user.save()
                return new_user

        except Exception as e:
            logging.error(f"Error in add_user_function: {str(e)}")
            raise

    @classmethod
    async def set_working_hours_function(
        cls,
        user_id: str,
        working_hours_data: List[dict]
    ):
        """
        Set working hours for a user. This replaces any existing working hours.
        working_hours is a single list of WorkingHours objects.
        
        Args:
            user_id (str): The ID of the user to update
            working_hours_data (List[dict]): List of working hours dictionaries with 'start_time' and 'end_time'
            
        Returns:
            dict: Status and message indicating success or failure
        """
        try:
            # Validate input
            if not user_id or not working_hours_data:
                return {"status": "error", "message": "⚠️ 用戶ID和工作時間資料不能為空"}

            try:
                object_id = ObjectId(user_id)
            except Exception:
                return {"status": "error", "message": f"⚠️ 無效的用戶ID格式: {user_id}"}

            # Find the user
            user = await cls.find_one(cls.id == object_id, cls.deleted_at == None)
            if not user:
                return {
                    "status": "error",
                    "message": f"⚠️ 找不到用戶資料，用戶ID: {user_id}",
                }

            # Validate and convert working hours data
            try:
                working_hours_list = []
                for hours_data in working_hours_data:
                    if not isinstance(hours_data, dict):
                        return {
                            "status": "error",
                            "message": "⚠️ 工作時間資料格式錯誤，必須為字典格式"
                        }
                    
                    if "start_time" not in hours_data or "end_time" not in hours_data:
                        return {
                            "status": "error",
                            "message": "⚠️ 工作時間資料必須包含 start_time 和 end_time"
                        }
                    
                    # Get start and end times
                    start_time = hours_data["start_time"]
                    end_time = hours_data["end_time"]
                    
                    # Validate time format (HH:MM)
                    if isinstance(start_time, str):
                        try:
                            # Validate format by parsing it
                            time.fromisoformat(start_time)
                        except ValueError:
                            return {
                                "status": "error",
                                "message": f"⚠️ 無效的開始時間格式: {start_time}，請使用 HH:MM 格式"
                            }
                    else:
                        return {
                            "status": "error",
                            "message": f"⚠️ 開始時間必須為字符串格式: {start_time}"
                        }
                    
                    if isinstance(end_time, str):
                        try:
                            # Validate format by parsing it
                            time.fromisoformat(end_time)
                        except ValueError:
                            return {
                                "status": "error",
                                "message": f"⚠️ 無效的結束時間格式: {end_time}，請使用 HH:MM 格式"
                            }
                    else:
                        return {
                            "status": "error",
                            "message": f"⚠️ 結束時間必須為字符串格式: {end_time}"
                        }
                    
                    # Validate time logic by comparing time objects
                    try:
                        start_time_obj = time.fromisoformat(start_time)
                        end_time_obj = time.fromisoformat(end_time)
                        if start_time_obj >= end_time_obj:
                            return {
                                "status": "error",
                                "message": "⚠️ 開始時間必須早於結束時間"
                            }
                    except ValueError:
                        return {
                            "status": "error",
                            "message": "⚠️ 時間格式驗證失敗"
                        }
                    
                    working_hours_list.append(WorkingHours(
                        start_time=start_time,
                        end_time=end_time
                    ))
                
            except Exception as e:
                logging.error(f"Error validating working hours data: {str(e)}")
                return {
                    "status": "error",
                    "message": f"⚠️ 工作時間資料驗證失敗: {str(e)}"
                }

            # Set working hours (replace any existing)
            user.working_hours = working_hours_list

            # Save the updated user
            await user.save()

            # Determine display name
            name = user.chinese_name if user.chinese_name else user.english_name

            logging.info(f"Successfully set working hours for user {user_id}")
            
            return {
                "status": "success",
                "message": f"✅ 成功為用戶 {name} 設置了 {len(working_hours_list)} 個工作時間段",
                "user_id": str(user.id),
                "working_hours": [working_hours.model_dump() for working_hours in user.working_hours]
            }
 
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error setting working hours for user {user_id}: {error_msg}", exc_info=True)
            return {"status": "error", "message": f"⚠️ 發生錯誤: {error_msg}"}

    @classmethod
    async def get_working_hours_function(cls, user_id: str):
        """
        Get working hours for a specific user.
        
        Args:
            user_id (str): The ID of the user
            
        Returns:
            dict: Status and working hours data
        """
        try:
            # Validate input
            if not user_id:
                return {"status": "error", "message": "⚠️ 用戶ID不能為空"}

            try:
                object_id = ObjectId(user_id)
            except Exception:
                return {"status": "error", "message": f"⚠️ 無效的用戶ID格式: {user_id}"}

            # Find the user
            user = await cls.find_one(cls.id == object_id, cls.deleted_at == None)
            if not user:
                return {
                    "status": "error",
                    "message": f"⚠️ 找不到用戶資料，用戶ID: {user_id}",
                }

            # Format working hours for response
            working_hours_data = []
            if user.working_hours:
                for hours in user.working_hours:
                    working_hours_data.append({
                        "start_time": hours.start_time,
                        "end_time": hours.end_time
                    })

            # Determine display name
            name = user.chinese_name if user.chinese_name else user.english_name

            return {
                "status": "success",
                "message": f"✅ 成功獲取用戶 {name} 的工作時間",
                "user_id": str(user.id),
                "working_hours": working_hours_data,
                "work_type": user.work_type
            }

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error getting working hours for user {user_id}: {error_msg}", exc_info=True)
            return {"status": "error", "message": f"⚠️ 發生錯誤: {error_msg}"}

    @classmethod
    async def clear_working_hours_function(cls, user_id: str):
        """
        Clear all working hours for a specific user.
        
        Args:
            user_id (str): The ID of the user
            
        Returns:
            dict: Status and message indicating success or failure
        """
        try:
            # Validate input
            if not user_id:
                return {"status": "error", "message": "⚠️ 用戶ID不能為空"}

            try:
                object_id = ObjectId(user_id)
            except Exception:
                return {"status": "error", "message": f"⚠️ 無效的用戶ID格式: {user_id}"}

            # Find the user
            user = await cls.find_one(cls.id == object_id, cls.deleted_at == None)
            if not user:
                return {
                    "status": "error",
                    "message": f"⚠️ 找不到用戶資料，用戶ID: {user_id}",
                }

            # Clear working hours
            user.working_hours = None
            await user.save()

            # Determine display name
            name = user.chinese_name if user.chinese_name else user.english_name

            logging.info(f"Successfully cleared working hours for user {user_id}")
            return {
                "status": "success",
                "message": f"✅ 成功清除用戶 {name} 的所有工作時間",
                "user_id": str(user.id)
            }

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error clearing working hours for user {user_id}: {error_msg}", exc_info=True)
            return {"status": "error", "message": f"⚠️ 發生錯誤: {error_msg}"}

    @classmethod
    async def add_unprocessed_card_function(cls, mobile: List[str], card_images: List[str]):
        try:
            from infrastructure.database.database_connection import get_grid_fs

            grid_fs = await get_grid_fs()
            # Convert mobile to list if it's a string
            mobile_list = [mobile] if isinstance(mobile, str) else mobile
            
            existing_user = await cls.find_one(
                cls.mobile == mobile, cls.deleted_at == None
            )
            if existing_user:
                # Initialize cards_unprocessed if it's None
                if existing_user.cards_unprocessed is None:
                    existing_user.cards_unprocessed = []

                # Process each card image: download and store binary data
                for card_image in card_images:
                    card_image_bytes = await download_image_to_memory(card_image)
                    if card_image_bytes:  # Check if download was successful
                        # Generate filename for the card image
                        import uuid

                        filename = f"unprocessed_card_{uuid.uuid4().hex}.jpg"

                        # Upload binary data directly to GridFS using Motor's async method
                        from io import BytesIO

                        card_image_stream = BytesIO(card_image_bytes)

                        card_image_id = await grid_fs.upload_from_stream(
                            filename=filename, source=card_image_stream
                        )

                        # Store the GridFS ID in the user's document
                        existing_user.cards_unprocessed.append(str(card_image_id))

                # Save once after processing all images
                await existing_user.save()

                # Create a properly formatted URL list
                url_list_formatted = []
                for i, card_image_id in enumerate(existing_user.cards_unprocessed, 1):
                    url = (
                        f"{base_url}/user/all-unprocessed-cards/{card_image_id}/preview"
                    )
                    url_list_formatted.append(f"{i}. {url}")

                # Join the URLs with newlines for better readability
                urls_text = "\n".join(url_list_formatted)

                message = f"已成功添加{len(card_images)}張未處理嘅卡片。\n\n圖片嘅網址如下: \n{urls_text}"

                return {"status": "success", "message": message}
            else:
                raise ValueError(f"⚠️ 呢啲手機號碼為{mobile_list}嘅用戶不存在。")

        except Exception as e:
            logging.error(f"Error in add_unprocessed_card_function: {str(e)}")
            raise


    @classmethod
    async def set_approvers_for_user_function(cls, user_id: str, approver_ids: List[str]):
        try:
            user_info = await cls.find_one(cls.id == ObjectId(user_id), cls.deleted_at == None)
            if not user_info:
                return {"status": "error", "message": "⚠️ 找不到用戶資料，用戶ID: {user_id}"}
            
            if user_info.approved_by is None:
                user_info.approved_by = [str(approver_id) for approver_id in approver_ids]
            else:
                user_info.approved_by.extend([str(approver_id) for approver_id in approver_ids]) #append the new approver ids to the existing approved_by list
            await user_info.save()
            return {"status": "success", 
                    "message": f"✅ 成功設置用戶 {user_info.chinese_name if user_info.chinese_name else user_info.english_name} 的批准者",
                    "user_id": str(user_info.id),
                    "approved_by": [str(approver_id) for approver_id in user_info.approved_by]}
        except Exception as e:
            logging.error(f"Error in set_approvers_for_user_function: {str(e)}")
            raise


    @classmethod
    async def set_approvers_for_work_type_function(cls, work_type: WorkType, approver_ids: List[str]):
        try:
            user_list = await cls.find(cls.work_type == work_type, cls.deleted_at == None).to_list()
            if not user_list:
                return {"status": "error", "message": f"⚠️ 找不到工作類型資料，工作類型: {work_type}"}
            updated_users = 0
            for user in user_list:
                if user.approved_by is None:
                    user.approved_by = [str(approver_id) for approver_id in approver_ids]
                else:
                    # Add new approver IDs without duplicates
                    existing_approvers = set(user.approved_by)
                    new_approvers = [str(approver_id) for approver_id in approver_ids if str(approver_id) not in existing_approvers]
                    user.approved_by.extend(new_approvers)
                await user.save()
                updated_users += 1
            return {"status": "success", 
                    "message": f"✅ 成功設置工作類型 {work_type} 的批准者，更新了 {updated_users} 個用戶",
                    "work_type": work_type,
                    "updated_users": updated_users,
                    "approved_by": [str(approver_id) for approver_id in approver_ids]}
        except Exception as e:
            logging.error(f"Error in set_approvers_for_work_type_function: {str(e)}")
            raise


    @classmethod
    async def delete_one_user_function(cls, user_id_param: str):

        # Store the parameter in a local variable to avoid any name conflicts
        user_id = user_id_param
            
        try:
            from src.models.attendance_record_model import AttendanceRecord
            from src.models.application_and_approval_model import ApplicationAndApproval
            from src.models.worker_project_model import WorkerProjectContractInfo
            
            # Validate user_id format
            if not user_id or not user_id.strip():
                return {"status": "error", "message": "⚠️ 用戶ID不能為空"}
            
            try:
                object_id = ObjectId(user_id)
            except Exception:
                return {"status": "error", "message": f"⚠️ 無效的用戶ID格式: {user_id}"}
            
            # Find the user
            user = await cls.find_one(cls.id == object_id, cls.deleted_at == None)
            if not user:
                return {"status": "error", "message": f"⚠️ 找不到用戶資料，用戶ID: {user_id}"}
            
            user_name = user.chinese_name if user.chinese_name else user.english_name
            
            # Soft delete all related attendance records
            # Use a filter dict instead of class field comparison to avoid AttributeError
            attendance_records = await AttendanceRecord.find(
                {"worker_id": user_id, "deleted_at": None}
            ).to_list()
            
            for attendance_record in attendance_records:
                attendance_record.deleted_at = get_this_moment()
                await attendance_record.save()
            
            logging.info(f"Soft deleted {len(attendance_records)} attendance records for user {user_id}")
            
            # Soft delete all related application and approval records
            applications = await ApplicationAndApproval.find(
                {"user_id": user_id, "deleted_at": None}
            ).to_list()
            
            for application in applications:
                application.deleted_at = get_this_moment()
                await application.save()
            
            logging.info(f"Soft deleted {len(applications)} application records for user {user_id}")
            
            # Soft delete all related worker project contract info
            contract_records = await WorkerProjectContractInfo.find(
                {"user_id": user_id, "deleted_at": None}
            ).to_list()
            
            for contract_record in contract_records:
                contract_record.deleted_at = get_this_moment()
                await contract_record.save()
            
            logging.info(f"Soft deleted {len(contract_records)} contract records for user {user_id}")
            
            # Finally, soft delete the user itself
            user.deleted_at = get_this_moment()
            await user.save()
            
            return {
                "status": "success", 
                "message": f"✅ 成功刪除用戶 {user_name} 及其相關記錄",
                "details": {
                    "attendance_records_deleted": len(attendance_records),
                    "applications_deleted": len(applications),
                    "contract_records_deleted": len(contract_records)
                }
            }
        except NameError as ne:
            error_msg = f"NameError: {str(ne)} - Check if variable 'user_id' is defined"
            logging.error(f"Error in delete_one_user_function: {error_msg}", exc_info=True)
            return {
                "status": "error",
                "message": f"⚠️ 刪除用戶時發生錯誤: {error_msg}"
            }
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logging.error(f"Error in delete_one_user_function: {error_msg}", exc_info=True)
            return {
                "status": "error",
                "message": f"⚠️ 刪除用戶時發生錯誤: {error_msg}"
            }
        