from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
import logging
from bson import ObjectId

from src.models.attendance_record_model import AttendanceRecord
from src.models.user_model import User, WorkType
from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day


class AttendanceRecordHelpers:
    
    @classmethod
    async def lunch_overtime_application_function(
        cls,
        user_id: str,
        attendance_date: date,
    ) -> dict:
        """
        Apply for lunch overtime application with comprehensive validation and business rules.
        
        Args:
            user_id: User ID (must be valid ObjectId string)
            attendance_date: Date for lunch overtime application (cannot be in the future)
            
        Returns:
            dict: {
                "status": "success" | "error",
                "message": str,
                "data": Optional[dict] - Additional information on success
            }
        """
        try:
            # 1. Input validation
            if not user_id or not isinstance(user_id, str):
                return {
                    "status": "error", 
                    "message": "User ID is required and must be a valid string"
                }
            
            if not attendance_date or not isinstance(attendance_date, date):
                return {
                    "status": "error", 
                    "message": "Attendance date is required and must be a valid date"
                }
            
            # 2. Validate ObjectId format
            try:
                ObjectId(user_id)
            except Exception:
                return {
                    "status": "error", 
                    "message": "Invalid user ID format"
                }
            
            # 3. Check if date is in the future
            today = get_this_day()
            if attendance_date > today:
                return {
                    "status": "error", 
                    "message": f"Cannot apply for lunch overtime on future date ({attendance_date}). Only current or past dates are allowed."
                }
            
            # 4. Verify user exists and is active
            user = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)
            if not user:
                return {
                    "status": "error", 
                    "message": f"User with ID {user_id} not found or has been deleted"
                }
            
            logging.info(f"Processing lunch overtime application for user {user_id} on {attendance_date}")
            
            # 5. Find attendance record
            attendance_record = await AttendanceRecord.find_one(
                AttendanceRecord.worker_id == user_id, 
                AttendanceRecord.attendance_date == attendance_date, 
                AttendanceRecord.deleted_at == None
            )
            
            if not attendance_record:
                return {
                    "status": "error", 
                    "message": f"Sorry, no attendance record found for you on {attendance_date}. Please ensure you have checked in for this date."
                }
            
            # 6. Check if lunch overtime already exists
            if attendance_record.lunch_overtime:
                return {
                    "status": "error", 
                    "message": f"Lunch overtime application already exists for {attendance_date}. Cannot apply twice for the same date."
                }
            
            # 7. Business rule: Check if attendance record has any shifts
            if not attendance_record.shifts:
                return {
                    "status": "error", 
                    "message": f"No shifts found for {attendance_date}. Lunch overtime can only be applied when there are active shifts."
                }
            
            # 8. Apply lunch overtime
            attendance_record.lunch_overtime = True
            attendance_record.updated_at = get_this_moment()
            await attendance_record.save()
            
            logging.info(f"Successfully applied lunch overtime for user {user_id} on {attendance_date}")
            
            return {
                "status": "success", 
                "message": f"Lunch overtime application successful for {attendance_date}",
                "data": {
                    "user_id": user_id,
                    "attendance_date": attendance_date.isoformat(),
                    "applied_at": get_this_moment().isoformat(),
                    "attendance_record_id": str(attendance_record.id)
                }
            }
            
        except ValueError as e:
            logging.error(f"Validation error in lunch_overtime_application_function: {e}")
            return {
                "status": "error", 
                "message": f"Invalid input data: {str(e)}"
            }
        except Exception as e:
            logging.error(f"Unexpected error in lunch_overtime_application_function for user {user_id} on {attendance_date}: {e}", exc_info=True)
            return {
                "status": "error", 
                "message": "An unexpected error occurred while processing your lunch overtime application. Please try again later."
            }
    
    @classmethod
    async def cancel_lunch_overtime_application_function(
        cls,
        user_id: str,
        attendance_date: date,
    ) -> dict:
        """
        Cancel/revoke an existing lunch overtime application.
        
        Args:
            user_id: User ID (must be valid ObjectId string)
            attendance_date: Date for which to cancel lunch overtime application
            
        Returns:
            dict: {
                "status": "success" | "error",
                "message": str,
                "data": Optional[dict] - Additional information on success
            }
        """
        try:
            # 1. Input validation (reuse same validation as apply function)
            if not user_id or not isinstance(user_id, str):
                return {
                    "status": "error", 
                    "message": "User ID is required and must be a valid string"
                }
            
            if not attendance_date or not isinstance(attendance_date, date):
                return {
                    "status": "error", 
                    "message": "Attendance date is required and must be a valid date"
                }
            
            # 2. Validate ObjectId format
            try:
                ObjectId(user_id)
            except Exception:
                return {
                    "status": "error", 
                    "message": "Invalid user ID format"
                }
            
            # 3. Check if date is in the future (can't cancel future applications)
            today = get_this_day()
            if attendance_date > today:
                return {
                    "status": "error", 
                    "message": f"Cannot cancel lunch overtime for future date ({attendance_date}). Only current or past dates are allowed."
                }
            
            # 4. Verify user exists and is active
            user = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)
            if not user:
                return {
                    "status": "error", 
                    "message": f"User with ID {user_id} not found or has been deleted"
                }
            
            logging.info(f"Processing lunch overtime cancellation for user {user_id} on {attendance_date}")
            
            # 5. Find attendance record
            attendance_record = await AttendanceRecord.find_one(
                AttendanceRecord.worker_id == user_id, 
                AttendanceRecord.attendance_date == attendance_date, 
                AttendanceRecord.deleted_at == None
            )
            
            if not attendance_record:
                return {
                    "status": "error", 
                    "message": f"Sorry, no attendance record found for you on {attendance_date}."
                }
            
            # 6. Check if lunch overtime exists to cancel
            if not attendance_record.lunch_overtime:
                return {
                    "status": "error", 
                    "message": f"Sorry, no lunch overtime application found for you on {attendance_date}. Nothing to cancel."
                }
            
            # 7. Cancel lunch overtime
            attendance_record.lunch_overtime = False
            attendance_record.updated_at = get_this_moment()
            await attendance_record.save()
            
            logging.info(f"Successfully cancelled lunch overtime for user {user_id} on {attendance_date}")
            
            return {
                "status": "success", 
                "message": f"Lunch overtime application cancelled for {attendance_date}",
                "data": {
                    "user_id": user_id,
                    "attendance_date": attendance_date.isoformat(),
                    "cancelled_at": get_this_moment().isoformat(),
                    "attendance_record_id": str(attendance_record.id)
                }
            }
            
        except ValueError as e:
            logging.error(f"Validation error in cancel_lunch_overtime_application_function: {e}")
            return {
                "status": "error", 
                "message": f"Invalid input data: {str(e)}"
            }
        except Exception as e:
            logging.error(f"Unexpected error in cancel_lunch_overtime_application_function for user {user_id} on {attendance_date}: {e}", exc_info=True)
            return {
                "status": "error", 
                "message": "An unexpected error occurred while cancelling your lunch overtime application. Please try again later."
            }
    
    @classmethod
    async def get_lunch_overtime_status_function(
        cls,
        user_id: str,
        attendance_date: date,
    ) -> dict:
        """
        Get the lunch overtime status for a specific user and date.
        
        Args:
            user_id: User ID (must be valid ObjectId string)
            attendance_date: Date to check lunch overtime status
            
        Returns:
            dict: {
                "status": "success" | "error",
                "message": str,
                "data": Optional[dict] - Status information
            }
        """
        try:
            # 1. Input validation
            if not user_id or not isinstance(user_id, str):
                return {
                    "status": "error", 
                    "message": "User ID is required and must be a valid string"
                }
            
            if not attendance_date or not isinstance(attendance_date, date):
                return {
                    "status": "error", 
                    "message": "Attendance date is required and must be a valid date"
                }
            
            # 2. Validate ObjectId format
            try:
                ObjectId(user_id)
            except Exception:
                return {
                    "status": "error", 
                    "message": "Invalid user ID format"
                }
            
            # 3. Verify user exists and is active
            user = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)
            if not user:
                return {
                    "status": "error", 
                    "message": f"User with ID {user_id} not found or has been deleted"
                }
            
            # 4. Find attendance record
            attendance_record = await AttendanceRecord.find_one(
                AttendanceRecord.worker_id == user_id, 
                AttendanceRecord.attendance_date == attendance_date, 
                AttendanceRecord.deleted_at == None
            )
            
            if not attendance_record:
                return {
                    "status": "success", 
                    "message": f"Sorry, no attendance record found on {attendance_date}",
                    "data": {
                        "user_id": user_id,
                        "attendance_date": attendance_date.isoformat(),
                        "has_attendance_record": False,
                        "lunch_overtime_status": None,
                        "can_apply": False,
                        "reason": "No attendance record exists for this date"
                    }
                }
            
            # 5. Return lunch overtime status
            lunch_overtime_status = attendance_record.lunch_overtime
            can_apply = not lunch_overtime_status and len(attendance_record.shifts) > 0
            
            return {
                "status": "success", 
                "message": f"Lunch overtime status retrieved for {attendance_date}",
                "data": {
                    "user_id": user_id,
                    "attendance_date": attendance_date.isoformat(),
                    "has_attendance_record": True,
                    "lunch_overtime_status": lunch_overtime_status,
                    "can_apply": can_apply,
                    "can_cancel": lunch_overtime_status,
                    "has_shifts": len(attendance_record.shifts) > 0,
                    "attendance_record_id": str(attendance_record.id),
                    "last_updated": attendance_record.updated_at.isoformat() if attendance_record.updated_at else None
                }
            }
            
        except ValueError as e:
            logging.error(f"Validation error in get_lunch_overtime_status_function: {e}")
            return {
                "status": "error", 
                "message": f"Invalid input data: {str(e)}"
            }
        except Exception as e:
            logging.error(f"Unexpected error in get_lunch_overtime_status_function for user {user_id} on {attendance_date}: {e}", exc_info=True)
            return {
                "status": "error", 
                "message": "An unexpected error occurred while retrieving lunch overtime status. Please try again later."
            }