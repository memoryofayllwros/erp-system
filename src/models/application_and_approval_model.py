from datetime import datetime
from typing import List, Optional, Tuple
from enum import Enum
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from beanie import Document
import logging
from datetime import date
import pytz
from src.models.user_model import User
from bson import ObjectId
from src.models.user_model import User
from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day, HK_TZ



class ApplicationStatus(str, Enum):
    """Application status types"""
    PENDING = "pending"  # Waiting for approver response
    APPROVED = "approved"  # Approved by approver
    REJECTED = "rejected"  # Rejected by approver

class LeaveType(str, Enum):
    SICK_LEAVE = "sick leave"
    COMPENSATORY_LEAVE = "compensatory leave"
    ANNUAL_LEAVE = "annual leave"
    OTHER_LEAVE = "other leave"

class EachApprovalStatus(BaseModel):
    approver_id: str
    approval_status: ApplicationStatus
    approval_timestamp: datetime #hk timezone #the time when the approval_status changes from pending to approved or rejected

class LeaveApplicationInfo(BaseModel):
    start_date: date
    end_date: date
    is_half_day: bool = False # True for half day, False for full day
    is_upper_half_day: Optional[bool] = None # True for morning, False for afternoon
    leave_reason: Optional[str] = None
    certificate_file_ids: Optional[List[str]] = None

    @model_validator(mode='after')
    def validate_half_day_logic(self):
        """Validate the relationship between is_half_day and is_upper_half_day
        
        - if is_half_day is True, then is_upper_half_day must be either True or False (not None)
        - if is_half_day is False, then is_upper_half_day must be None
        """
        if self.is_half_day:
            if self.is_upper_half_day is None:
                raise ValueError("is_upper_half_day must be either True or False if is_half_day is True")
        else:
            if self.is_upper_half_day is not None:
                raise ValueError("is_upper_half_day must be None if is_half_day is False")
        return self


class ApplicationInfo(BaseModel):
    leave_application_info: Optional[LeaveApplicationInfo] = None #only when application_type is LEAVE

class ApplicationAndApproval(Document):
    application_code: str 
    user_id: str
    project_id: Optional[str] = None
    application_type: LeaveType
    application_info: ApplicationInfo
    approval_status: List[EachApprovalStatus] = []
    leave_policy_breach: bool = False # True if the application breaches the leave policy, False otherwise 
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "application_and_approval_collection"

    class Config:
        arbitrary_types_allowed = True

    """
    Leave Policy: 
    1. user can instantly apply one day or half day leave application, that is, can leave without approval
    2. if the leave period is more than 1 day, the application should apply 3 days before the start date to be pending for ex-ante approval -> response mentioning the approvers would be notified and give replies within 3 days.
    3. leave_policy_breach is True if the application breaches the leave policy, False otherwise. -> response mentioning the leave policy breach, even though the application can be submitted successfully.
    4. Consider workers' holidays (HK bank holidays and labour holidays) when calculating the leave period.
    """

    @field_validator('approval_status', mode='before')
    @classmethod
    def validate_approval_status(cls, v):
        """Handle migration from old string format to new list format"""
        if isinstance(v, str):
            # Legacy format: convert string to list with default approver
            logging.warning(f"Converting legacy approval_status from string '{v}' to list format")
            return [
                EachApprovalStatus(
                    approver_id="legacy_migration",
                    approval_status=ApplicationStatus(v),
                    approval_timestamp=get_this_moment()
                )
            ]
        elif isinstance(v, list):
            # Already in correct format
            return v
        else:
            # Default to empty list
            return []


    @computed_field
    @property
    def ex_ante_apply_required(self) -> bool:
        """Determine if ex-ante approval is required based on leave duration.
        
        Ex-ante approval is required if the leave period is more than 1 day.
        """
        if self.application_info.leave_application_info:
            start_date = self.application_info.leave_application_info.start_date
            end_date = self.application_info.leave_application_info.end_date
            days = (end_date - start_date).days + 1  # +1 because inclusive
            return days > 1
        return False


    @classmethod
    async def _get_application_code(cls) -> str:
        """Get the application code for the application"""
        try:
            today = get_this_day()
            # Get the first day of the current month
            first_day_of_month = datetime(today.year, today.month, 1, 0, 0, 0, tzinfo=HK_TZ)
            # Get the last day of the current month
            if today.month == 12:
                next_month = datetime(today.year + 1, 1, 1, 0, 0, 0, tzinfo=HK_TZ)
            else:
                next_month = datetime(today.year, today.month + 1, 1, 0, 0, 0, tzinfo=HK_TZ)
            
            count = await ApplicationAndApproval.find(
                ApplicationAndApproval.created_at >= first_day_of_month,
                ApplicationAndApproval.created_at < next_month,
                ApplicationAndApproval.deleted_at == None
            ).count() #count the number of applications this month, if the application is not deleted
            sequence_number = count + 1
            if sequence_number < 10:
                sequence_number = f"0{sequence_number}"
            elif sequence_number < 100:
                sequence_number = f"{sequence_number}"
            return f"WA-{today.strftime('%Y%m')}-{sequence_number}" #WA-202501-01
        except Exception as e:
            logging.error(f"Failed to get application code: {str(e)}")
            return None



    @classmethod
    async def read_my_leave_records_function(cls, user_id: str) -> dict:
        """Read my leave records for a user"""
        try:
            user_info = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)

            if not user_info:
                return {
                    "status": "error",
                    "message": "User not found"
                }

            leave_records = await cls.find(
                cls.user_id == user_id,
                cls.deleted_at == None
            ).to_list()

            return {
                "status": "success",
                "message": "Leave records read successfully",
                "data": leave_records
            }
        except Exception as e:
            logging.error(f"Failed to read my leave records: {str(e)}")
            return {
                "status": "error",
                "message": "Failed to read leave records"
            }


    @classmethod
    async def delete_leave_application_function(
        cls,
        application_id: str
    ) -> dict:
        """Delete a leave application"""
        try:
            application = await cls.find_one(cls.id == ObjectId(application_id), cls.deleted_at == None)
            if not application:
                return {
                    "status": "error",
                    "message": "Application not found"
                }
            application.deleted_at = get_this_moment()
            await application.save()
            logging.info(f"Deleted leave application: {application_id}")
            return {
                "status": "success",
                "message": "Leave application deleted successfully"
            }
        except Exception as e:
            logging.error(f"Failed to delete leave application: {str(e)}")
            return {
                "status": "error",
                "message": "Failed to delete leave application"
            }



    @classmethod
    async def find_by_application_code(cls, application_code: str) -> Optional["ApplicationAndApproval"]:
        """Find application by application code"""
        try:
            return await cls.find_one(
                cls.application_code == application_code,
                cls.deleted_at == None
            )
        except Exception as e:
            logging.error(f"Failed to find application by code: {str(e)}")
            return None

    @classmethod
    async def read_all_leave_records_function(cls) -> List["ApplicationAndApproval"]:
        """Read all leave records, grouped by user_id"""
        try:
            all_leave_records = await cls.find(
                cls.deleted_at == None
            ).to_list()
            grouped_leave_records = {}
            for record in all_leave_records:
                if record.user_id not in grouped_leave_records:
                    grouped_leave_records[record.user_id] = []
                grouped_leave_records[record.user_id].append(record)
            return {
                "status": "success",
                "message": "All leave records read successfully",
                "data": grouped_leave_records
            }

        except Exception as e:
            logging.error(f"Failed to read all leave records: {str(e)}")
            return {
                "status": "error",
                "message": "Failed to read all leave records"
            }