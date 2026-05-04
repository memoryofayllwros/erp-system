# Integration Guide: Updating Your Existing AttendanceProcessor
import logging
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class CheckInData:
    user_waba: str
    user_id: str
    project_id: str
    project_code: str
    lat: str
    lon: str
    accuracy: str
    timestamp: str


class AttendanceProcessor:
    async def process_checkin_for_attendance(
        self, checkin_data: CheckInData
    ) -> Dict[str, Any]:

        try:

            attendance_result = await self._create_attendance_record(checkin_data)

            if not self._is_valid_attendance_result(attendance_result):
                return await self._handle_invalid_result(
                    checkin_data.user_waba, attendance_result
                )

            return attendance_result

        except Exception as e:
            return await self._handle_critical_error(checkin_data.user_waba, e)

    async def _create_attendance_record(
        self, checkin_data: CheckInData
    ) -> Dict[str, Any]:
        """
        Updated method using the improved AttendanceRecord system
        """
        # Import the improved service
        from src.models.attendance_record_model import AttendanceRecord

        # Convert datetime to string format expected by the system
        logger.info(
            f"🔄 Processing attendance with improved model: {checkin_data.timestamp}, type: {type(checkin_data.timestamp)}"
        )

        # Use the enhanced attendance recording system
        return await AttendanceRecord.add_worker_attendance_record(
            project_id=checkin_data.project_id,
            user_id=checkin_data.user_id,
            latitude=checkin_data.lat,
            longitude=checkin_data.lon,
            accuracy=checkin_data.accuracy,
            timestamp=checkin_data.timestamp,
            attendance_method=True,
        )

    def _is_valid_attendance_result(self, attendance_result: Any) -> bool:
        """Updated validation for new response format"""
        return isinstance(attendance_result, dict) and "status" in attendance_result

    async def _handle_invalid_result(
        self, user_waba: str, attendance_result: Any
    ) -> Dict[str, Any]:
        """Handles unexpected results from attendance creation"""
        logger.warning(f"⚠️ 無效的打卡結果 for {user_waba}: {attendance_result}")
        return {
            "status": "error",
            "message": "簽到記錄保存時發生錯誤，請稍後再試\n\nAn error occurred while saving the attendance record, please try again later.",
        }

    async def _handle_critical_error(
        self, user_waba: str, error: Exception
    ) -> Dict[str, Any]:
        """Handles exceptions during check-in processing"""
        logger.error(
            f"❌ 發生系統錯誤在打卡處理 for {user_waba}: {error}", exc_info=True
        )
        return {
            "status": "error",
            "message": "處理簽到時發生錯誤，請稍後再試\n\nAn error occurred while processing the attendance, please try again later.",
        }


# Updated process_attendance_record function
async def process_attendance_record(
    user_waba: str,
    lat: str,
    lon: str,
    accuracy: str,
    timestamp: str,
    project_id: str = None,
) -> Dict[str, Any]:
    """
    Updated orchestration function using new attendance system.
    """
    # If project_id is not provided, try to get it from GPS location
    if project_id is None:
        from src.chatbot_service.llm_prompts.attendance_via_gps_templates import \
            progressive_location_gps_match

        document_response = await progressive_location_gps_match(lat, lon)
        logger.info(
            f"📍 document_response from GPS match: {document_response}, type: {type(document_response)}"
        )

        project_id = document_response.get("project_id")
        project_code = document_response.get("project_code")
        message = document_response.get("message")

        if project_id is None:
            logger.warning(f"❌ 未找到匹配項目: {message}")
            return {"status": "error", "message": message}
    else:
        from bson import ObjectId

        from src.models.project_model import Project
        from infrastructure.database.database_connection import get_database

        # Ensure database is initialized
        await get_database()

        try:
            project = await Project.find_one(
                Project.id == ObjectId(project_id), Project.deleted_at == None
            )
            project_code = project.project_code if project else None
            logger.info(
                f"📍 Using provided project_id: {project_id}, found project_code: {project_code}"
            )
        except Exception as e:
            logger.error(f"❌ Error getting project info: {e}")
            return {
                "status": "error",
                "message": "處理簽到時發生錯誤，請稍後再試\n\nAn error occurred while processing the attendance, please try again later.",
            }

    from src.utils.standardization_helpers import validate_mobile_from_whatsapp
    sender_info = await validate_mobile_from_whatsapp(user_waba)

    user_id = str(sender_info.get("_id"))
    if user_id is None:
        return {
            "status": "error",
            "message": "找不到用戶記錄",
            "data": None,
        }

    checkin_data = CheckInData(
        user_waba=user_waba,
        user_id=user_id,
        project_id=project_id,
        project_code=project_code,
        lat=lat,
        lon=lon,
        accuracy=accuracy,
        timestamp=timestamp,
    )

    processor = AttendanceProcessor()
    return await processor.process_checkin_for_attendance(checkin_data)
