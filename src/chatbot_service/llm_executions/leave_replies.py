


import logging
from datetime import datetime, date, timedelta
from typing import Optional
from bson import ObjectId
import json
from src.utils.standardization_helpers import validate_mobile_from_whatsapp
from src.models.application_and_approval_model import ApplicationAndApproval
from src.models.project_model import Project
from src.models_business_logic.application_and_approval_helpers import ANA_HELPERS
from src.models.user_model import User, WorkType
from src.message_templates.leave_application_notification_templates import send_leave_application_notification_message

async def _format_leave_period_text(start_date, 
                                    end_date, 
                                    is_half_day: bool,
                                    is_upper_half_day: Optional[bool], 
                                    work_type: WorkType
                                    ) -> str:
        """_format_leave_period_text """
        if isinstance(start_date, str):
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            start = start_date
            
        if isinstance(end_date, str):
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = end_date

        calendar_days, working_days = ANA_HELPERS.calculate_leave_duration(start, end, is_upper_half_day if is_half_day else None, work_type)
        
        if start == end:
            formatted_leave_period_text = f"{start.strftime('%Y-%m-%d')} ({calendar_days} Calendar Day(s), {working_days} Working Day(s))"
        else:
            formatted_leave_period_text = f"{start.strftime('%Y-%m-%d')} To {end.strftime('%Y-%m-%d')} ({calendar_days} Calendar Day(s), {working_days} Working Day(s))"

        return formatted_leave_period_text



async def read_my_leave_records_by_chatbot(sender: str) -> dict:
    """Read my leave records for a user"""
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        if not sender_info:
            return {"status": "error", "message": "Invalid sender. Please register first."}
        sender_id = str(sender_info.id)
        sender_name = sender_info.english_name or sender_info.chinese_name
        greeting_message = f"Hi {sender_name}! ✅ Here are your leave records:\n你的請假記錄如下: \n\n"
        leave_records = await ApplicationAndApproval.read_my_leave_records_function(sender_id)

        logging.info(f"Leave records: {leave_records}")
        if leave_records["status"] == "error":
            return {"status": "error", "message": leave_records["message"]}
        else:
            leave_records_message = ""
            for index, leave_record in enumerate(leave_records["data"]):
                leave_records_message += f"{index + 1}. 📋 Application Code / 申請編號: {leave_record.application_code}\n"
                
                # Check if leave_application_info exists and has the required fields
                if (leave_record.application_info and 
                    leave_record.application_info.leave_application_info):
                    leave_info = leave_record.application_info.leave_application_info
                    # Get user's work_type
                    work_type = None
                    if hasattr(sender_info, "work_type"):
                        work_type = sender_info.work_type
                    leave_period_info = await _format_leave_period_text(leave_info.start_date, leave_info.end_date, leave_info.is_half_day, leave_info.is_upper_half_day, work_type)
                    logging.info(f"leave_period_info in leave replies: {leave_period_info}")
                    leave_records_message += f"📅 Duration / 天數: {leave_period_info}\n"
                else:
                    leave_records_message += f""
                
                leave_records_message += f"📝 Leave Type / 請假類型: {leave_record.application_type.value.title()}\n"
                leave_records_message += "  --------------------------------\n\n"

        return {"status": "success", "message": greeting_message + leave_records_message}
    except Exception as e:
        logging.error(f"Unexpected error in read_my_leave_records_by_chatbot: {str(e)}", exc_info=True)
        return {
            "status": "error", 
            "message": "An unexpected error occurred. Please contact support."
        }




async def add_leave_application_by_chatbot(
    sender: str, 
    start_date: str, 
    end_date: str, 
    is_half_day: bool,
    leave_type: str,
    is_upper_half_day: Optional[bool] = None, 
    leave_reason: Optional[str] = None,
    project_code: Optional[str] = None,
    medical_certificate: Optional[str] = None
) -> dict:
    """Handle leave application from chatbot interface"""
    
    try:
        # 1. Validate sender
        sender_info = await validate_mobile_from_whatsapp(sender)
        if not sender_info:
            return {"status": "error", "message": "Invalid sender. Please register first."}
            
        sender_name = sender_info.english_name or sender_info.chinese_name
        sender_id = str(sender_info.id)

        # 2. Parse and validate dates
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as e:
            return {
                "status": "error", 
                "message": f"Invalid date format. Please use YYYY-MM-DD format. Error: {str(e)}"
            }

        # 3. Resolve project
        project_id = None
        if not project_code:
            project_id = None
        else:
            project = await Project.find_one(
                Project.project_code == project_code, 
                Project.deleted_at == None
            )
            if not project:
                return {
                    "status": "error", 
                    "message": f"Project '{project_code}' not found. Please check the project code."
                }
            project_id = str(project.id)

            
        if leave_type == "sick leave":
            comfort_message = (
                "Your approvers have been notified. Wishing you a speedy recovery! 🌟\n"
                "你的審批人將會收到通知，祝你早日康復！🌟\n"
                "Please remember to submit your medical certificate after you're feeling better.\n"
                "康復後請記得提交醫生證明，謝謝！"
            )

        elif leave_type == "annual leave":
            comfort_message = (
                "Your approvers have been notified. Enjoy your well-deserved vacation! 🌴🌟\n"
                "你的審批人將會收到通知，祝你假期愉快！🌴🌟"
            )
        
        elif leave_type == "compensatory leave":
            comfort_message = (
                "Your approvers have been notified. Enjoy your well-deserved compensatory leave! 🌴🌟\n"
                "你的審批人將會收到通知，祝你補償假愉快！🌴🌟"
            )

        else:
            comfort_message = ""

        # 4. Create leave application via model method
        try:
            application = await ANA_HELPERS.add_leave_application_function(
                user_id=sender_id,
                start_date=start_date_obj,
                end_date=end_date_obj,
                leave_type=leave_type,
                is_half_day=is_half_day,
                is_upper_half_day=is_upper_half_day,
                project_id=project_id,
                leave_reason=leave_reason,
                medical_certificate=medical_certificate
            )
        except ValueError as e:
            # Handle validation errors from model layer
            return {"status": "error", "message": str(e)}
        
        if not application:
            return {
                "status": "error", 
                "message": "Failed to create leave application. Please try again or contact support."
            }

        # 5. Check if application creation was successful
        if application.get('status') != 'success':
            return {
                "status": "error", 
                "message": application.get('message', 'Failed to create leave application. Please try again or contact support.')
            }

        # 6. Format success response
        # Get user's work_type
        work_type = None
        if hasattr(sender_info, "work_type"):
            work_type = sender_info.work_type
        leave_period_text = await _format_leave_period_text(start_date, end_date, is_half_day, is_upper_half_day, work_type)
        
        # Get application code and policy notices from the response
        application_code = application.get('details', {}).get('application_code', 'N/A')

        is_policy_breach = application.get('details', {}).get('is_policy_breach', False)
        
        # Build policy notices section
        policy_notices_text = ""
        # Add policy breach warning if applicable
        if is_policy_breach:
            if not policy_notices_text:
                policy_notices_text = "\n\n📋 Important Notices / 重要通知:\n"
            policy_notices_text += "⚠️ Your application has been noted as not meeting policy requirements and may require special approval.\n"
            policy_notices_text += "⚠️ 你的申請未符合公司之請假政策，可能需要特別批准。\n"
        
        message = (
            f"Hi {sender_name}! ✅ Your leave application has been submitted successfully.\n你的請假申請已經提交成功。\n\n"
            f"📋 Application Code / 申請編號: {application_code}\n"
            f"📅 Duration / 天數: {leave_period_text}\n"
            f"📝 Leave Type / 請假類型: {leave_type.title()}\n"
            f"Approval Status / 審批狀態: {application.get('approval_status', 'Pending')}\n\n"
            f"{comfort_message}"
            f"{policy_notices_text}"
        )

        is_policy_breach_result = True if is_policy_breach else False
        
        alert_message_en = "⚠️ This application has been noted as not meeting policy requirements. Annual leave exceeding two consecutive days must be submitted at least 14 days prior to the start date." if is_policy_breach_result else None
        alert_message_zh = "⚠️ 此申請未符合公司之請假政策。連續兩天以上的年假申請，需於開始日期前至少14天提交。" if is_policy_breach_result else None

        list_of_approvers = await User.get_user_approvers(sender_id)
        logging.info(f"List of approvers: {list_of_approvers}")

        for receiver in list_of_approvers:
            receiver_name = receiver["approver_name"]
            receiver_waba = receiver["approver_waba"]

            await send_leave_application_notification_message(
                receiver_name=receiver_name,
                application_no=application_code,
                applicant_name=sender_name,
                leave_type=leave_type,
                leave_start_date=start_date,
                leave_end_date=end_date,
                leave_duration=leave_period_text,
                receiver_waba=receiver_waba,
                alert_message_en=alert_message_en if alert_message_en else None,
                alert_message_zh=alert_message_zh if alert_message_zh else None,
            )
            logging.info(f"Sent leave application notification to {receiver_name} ({receiver_waba})")

        return {"status": "success", "message": message}
        
    except Exception as e:
        logging.error(f"Unexpected error in add_leave_application_by_chatbot: {str(e)}", exc_info=True)
        return {
            "status": "error", 
            "message": "An unexpected error occurred. Please contact support."
        }
