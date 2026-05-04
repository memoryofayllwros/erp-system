from datetime import date
from typing import Dict, Any
from src.models_business_logic.attendance_record_helpers import AttendanceRecordHelpers
import logging
from src.utils.standardization_helpers import validate_mobile_from_whatsapp


async def add_lunch_overtime_by_chatbot(sender: str, lunch_ot_date: date):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        # user_id = str(sender_info.id)
        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        user_id = str(sender_info.id)

        function_result = await AttendanceRecordHelpers.lunch_overtime_application_function(
            user_id,
            lunch_ot_date,
        )
        logging.info(f"function_result in add_lunch_overtime_by_chatbot is: {function_result}")

        # Check if the function was successful
        if function_result.get("status") == "success":
            response_message = f"Hi, {sender_name}!"
            response_message += f"✅ Your lunch overtime application for {lunch_ot_date} has been recorded successfully.\n你嘅{lunch_ot_date}午膳時間加班申請已經記錄成功。\n\n"
            response_message += f"📅 Date / 日期: {lunch_ot_date}\n"
            response_message += f"📝 Type / 類型: Lunch Overtime\n"
            response_message += f"📝 Status / 狀態: Applied\n"
            
            # Safely access applied_at if data exists
            #if function_result.get('data'):
            #    response_message += f"📝 Applied At / 申請時間: {function_result.get('data').get('applied_at')}\n"
            
            response_message += f"📝 Applied By / 申請人: {sender_name}\n"
            return response_message
        else:
            # Return the error message from the function result
            error_message = function_result.get('message', 'Unknown error occurred')
            logging.warning(f"Lunch overtime application failed: {error_message}")
            return error_message
    except Exception as e:
        error_message = f"Sorry, I couldn't process your lunch overtime application. Please try again later. {str(e)}"
        logging.error(f"Error in add_lunch_overtime_by_chatbot: {error_message}")
        return f"{error_message}"