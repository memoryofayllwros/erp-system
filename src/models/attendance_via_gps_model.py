import logging
from datetime import date, datetime
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from beanie import Document
from pydantic import BaseModel, Field
from bson import ObjectId

from src.models.attendance_record_model import AttendanceRecord
from src.models.user_model import User
from src.message_templates.message_response_templates import send_whatsapp_message_back
from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day
logger = logging.getLogger(__name__)
BASE_URL = os.getenv("BASE_URL")


# ============================================================================
# DATA MODELS
# ============================================================================

class GpsAttendanceInfo(BaseModel):
    """GPS data for attendance check-in"""
    timestamp: datetime
    lan: Optional[str] = None  # latitude
    lon: Optional[str] = None  # longitude
    accuracy: Optional[str] = Field(default="0")


@dataclass
class GpsAttendanceData:
    """Structured check-in data for processing"""
    user_waba: str
    project_id: str
    project_code: str
    lat: str
    lon: str
    accuracy: str
    timestamp: datetime


# ============================================================================
# GPS ATTENDANCE MODEL (Collection)
# ============================================================================

class AttendanceViaGpsModel(Document):
    """
    Stores GPS-based attendance records before converting to main system.
    Acts as an intermediate collection for GPS check-ins.
    """
    user_id: str
    user_waba: Optional[str] = None
    project_id: str
    gps_attendance: GpsAttendanceInfo
    attendance_date: date = Field(default_factory=get_this_day)
    attendance_method: bool = Field(default=True)
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "attendance_via_gps_collection"

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    async def add_gps_attendance_info(
        user_id: str,
        user_waba: str,
        project_id: str,
        gps_attendance: GpsAttendanceInfo,
    ):
        """
        Main entry point for GPS-based attendance.
        Saves GPS data and converts to main attendance system.
        """
        try:
            # Save GPS attendance record
            attendance_record = AttendanceViaGpsModel(
                user_id=user_id,
                user_waba=user_waba,
                project_id=project_id,
                gps_attendance=gps_attendance
            )
            await attendance_record.save()
            logger.info(
                f"✅ Created GPS attendance record {attendance_record.id} for user {user_id}"
            )

            # Convert to main attendance system
            success = await AttendanceViaGpsModel.convert_to_main_attendance_system(
                attendance_record
            )

            if success:
                return attendance_record
            else:
                logger.error("Failed to convert GPS attendance to main system")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to create GPS attendance record: {str(e)}")
            return False

    @staticmethod
    async def convert_to_main_attendance_system(
        attendance_record: "AttendanceViaGpsModel",
    ) -> bool:
        """
        Converts GPS attendance to main attendance system using AttendanceProcessor.
        Sends WhatsApp notification to user.
        """
        try:
            # Extract GPS data
            latitude = attendance_record.gps_attendance.lan or "0.0"
            longitude = attendance_record.gps_attendance.lon or "0.0"
            accuracy = attendance_record.gps_attendance.accuracy or "10.0"
            actual_timestamp = attendance_record.gps_attendance.timestamp #time is in hk timezone, but naive datetime object
            user_waba = attendance_record.user_waba

            logging.info(f"actual_timestamp in convert_to_main_attendance_system: {actual_timestamp}")

            # Get user info
            user_info = await User.find_one(
                User.id == ObjectId(attendance_record.user_id),
                User.deleted_at == None
            )
            
            if not user_info:
                logger.error(f"❌ User not found for user_id: {attendance_record.user_id}")
                return False

            logger.info(f"📱 User WABA: {user_waba}")

            # Use AttendanceProcessor to create attendance record
            processor = AttendanceProcessor()
            
            # Get project info
            from src.models.project_model import Project
            project = await Project.find_one(
                Project.id == ObjectId(attendance_record.project_id),
                Project.deleted_at == None
            )
            project_code = project.project_code if project else None

            # Create GpsAttendanceData
            gps_attendance_data = GpsAttendanceData(
                user_waba=user_waba,
                project_id=attendance_record.project_id,
                project_code=project_code,
                lat=latitude,
                lon=longitude,
                accuracy=accuracy,
                timestamp=actual_timestamp,
            )

            # Process attendance
            attendance_result = await processor.process_gps_attendance_for_attendance(gps_attendance_data)
            logging.info(f"attendance_result in convert_to_main_attendance_system: {attendance_result}")

            # Send WhatsApp notification
            await AttendanceViaGpsModel._send_whatsapp_notification(user_waba, attendance_result)

            # Check result
            if attendance_result.get("status") == "success":
                logger.info(
                    f"✅ Successfully converted GPS attendance to main system for user {attendance_record.user_id}"
                )
                return True
            else:
                logger.error(
                    f"❌ Failed to convert GPS attendance: {attendance_result.get('message', 'Unknown error')}"
                )
                return False

        except Exception as e:
            logger.error(
                f"❌ Failed to convert GPS attendance to main system: {str(e)}",
                exc_info=True
            )
            return False


    @staticmethod
    async def _send_whatsapp_notification(user_waba: str, attendance_result: Dict[str, Any]):
        """Send WhatsApp notification about attendance result"""
        try:
            ENABLE_WABA_NOTIFICATIONS = (
                os.getenv("ENABLE_WABA_NOTIFICATIONS", "true").lower() == "true"
            )

            if not ENABLE_WABA_NOTIFICATIONS or not user_waba:
                logger.warning("WhatsApp notifications disabled or WABA not configured")
                return

            message = attendance_result.get("message", "")
            if isinstance(message, str):
                message = message.strip()
            elif hasattr(message, "__await__"):  # Check if it's awaitable
                try:
                    # Await the coroutine to get the actual message
                    message = await message
                    message = str(message).strip()
                except Exception as e:
                    logger.error(f"Error awaiting message coroutine: {e}")
                    message = "處理簽到時發生錯誤"
            else:
                # Handle other non-string objects
                logger.warning(f"Unexpected message type: {type(message)}")
                message = str(message)
                
            if not message:
                logger.warning("No message returned from attendance system")
                return

            # Customize message for GPS attendance
            gps_message = message.replace("簽到", "透過GPS簽到")

            if attendance_result.get("status") == "success":
                logger.info(f"📱 Sending WhatsApp confirmation to {user_waba}")
            else:
                logger.info(f"📱 Sending WhatsApp error message to {user_waba}")

            await send_whatsapp_message_back(gps_message, user_waba)
            logger.info(f"✅ WhatsApp message sent successfully to {user_waba}")

        except Exception as whatsapp_error:
            logger.error(f"❌ Failed to send WhatsApp message: {whatsapp_error}")


# ============================================================================
# ATTENDANCE PROCESSOR (Business Logic)
# ============================================================================

class AttendanceProcessor:
    """
    Handles attendance check-in processing with validation and error handling.
    Used by both GPS and direct attendance methods.
    """

    async def process_gps_attendance_for_attendance(self, gps_attendance_data: GpsAttendanceData
    ) -> Dict[str, Any]:
        """Main entry point for processing check-ins"""
        try:
            attendance_result = await self._create_attendance_record(gps_attendance_data)

            if not self._is_valid_attendance_result(attendance_result):
                return await self._handle_invalid_result(
                    gps_attendance_data.user_waba, attendance_result
                )

            return attendance_result

        except Exception as e:
            return await self._handle_critical_error(gps_attendance_data.user_waba, e)

    async def _create_attendance_record(
        self, gps_attendance_data: GpsAttendanceData
    ) -> Dict[str, Any]:
        """Create attendance record in main system"""
        logging.info(f"gps_attendance_data in _create_attendance_record: {gps_attendance_data}")

        logger.info(f"🔄 Processing attendance: {gps_attendance_data.timestamp}")

        # Extract user_id from user_waba
        from src.utils.standardization_helpers import validate_mobile_from_whatsapp
        sender_info = await validate_mobile_from_whatsapp(gps_attendance_data.user_waba)
        
        if not sender_info:
            logger.error(f"❌ Could not find user from user_waba: {gps_attendance_data.user_waba}")
            return {"status": "error", "message": "找不到用戶記錄"}
            
        # Get the user_id from the sender_info document
        user_id = str(sender_info.id)
        logger.info(f"Found user_id: {user_id} for user_waba: {gps_attendance_data.user_waba}")
            
        return await AttendanceRecord.add_worker_attendance_record(
            project_id=gps_attendance_data.project_id,
            user_id=user_id,
            latitude=gps_attendance_data.lat,
            longitude=gps_attendance_data.lon,
            accuracy=gps_attendance_data.accuracy,
            timestamp=gps_attendance_data.timestamp,
            attendance_method=True,
            image_file_ids=None,
        )

    def _is_valid_attendance_result(self, attendance_result: Any) -> bool:
        """Validate attendance result structure"""
        return isinstance(attendance_result, dict) and "status" in attendance_result

    async def _handle_invalid_result(
        self, user_waba: str, attendance_result: Any
    ) -> Dict[str, Any]:
        """Handle unexpected results"""
        logger.warning(f"⚠️ 無效的打卡結果 for {user_waba}: {attendance_result}")
        return {"status": "error", "message": "簽到記錄保存時發生錯誤，請稍後再試"}

    async def _handle_critical_error(
        self, user_waba: str, error: Exception
    ) -> Dict[str, Any]:
        """Handle critical errors during processing"""
        logger.error(
            f"❌ 發生系統錯誤在打卡處理 for {user_waba}: {error}", exc_info=True
        )
        return {"status": "error", "message": "處理簽到時發生錯誤，請稍後再試"}






