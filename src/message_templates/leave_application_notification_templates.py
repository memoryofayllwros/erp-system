import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from twilio.rest import Client
import logging
from typing import Optional

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")
chatbot_waba = os.getenv("WHATSAPP_NUMBER")
messaging_service_sid = os.getenv("MESSAGING_SERVICE_SID")

client = Client(account_sid, auth_token) if account_sid and auth_token else None

sick_leave_application_notification_id = os.getenv("SICK_LEAVE_APPLICATION_NOTIFICATION_ID")
annual_leave_application_notification_id = os.getenv("ANNUAL_LEAVE_APPLICATION_NOTIFICATION_ID")

async def send_leave_application_notification_message(
    receiver_name: str,
    application_no: str,
    applicant_name: str,
    leave_type: str,
    leave_start_date: str,
    leave_end_date: str,
    leave_duration: str,
    receiver_waba: str,
    alert_message_en: Optional[str] = None,
    alert_message_zh: Optional[str] = None,
):
    try:
        leave_type_normalized = leave_type.strip().lower()
        handlers = {
            "sick leave": send_sick_leave_application_notification_message,
            "annual leave": send_annual_leave_application_notification_message,
        }

        handler = handlers.get(leave_type_normalized)
        if not handler:
            logger.warning(f"Unsupported leave type '{leave_type}' for receiver {receiver_waba}")
            return None

        handler_kwargs = dict(
            receiver_name=receiver_name,
            application_no=application_no,
            applicant_name=applicant_name,
            leave_type=leave_type,
            leave_start_date=leave_start_date,
            leave_end_date=leave_end_date,
            leave_duration=leave_duration,
            receiver_waba=receiver_waba,
        )

        if handler is send_annual_leave_application_notification_message:
            handler_kwargs["alert_message_en"] = alert_message_en
            handler_kwargs["alert_message_zh"] = alert_message_zh

        return await handler(**handler_kwargs)
    except Exception as e:
        logger.error(
            f"Failed to send leave application notification message to {receiver_waba}: {str(e)}"
        )
        return None



async def send_sick_leave_application_notification_message(
    receiver_name: str,
    application_no: str,
    applicant_name: str,
    leave_type: str,
    leave_start_date: str,
    leave_end_date: str,
    leave_duration: str,
    receiver_waba: str):

    """
    message template:

    Hello {{1}},

    You’ve received a *Sick Leave Application Notification*.  Please check the details below.

    🏷️ Application No.: *{{2}}*
    👤 Applicant: *{{3}}*  
    📅 Leave Period: *{{4}}* - *{{5}}*  ({{6}} days)
    📝 Leave Type: *{{7}}*

    Thank you!  

    Best regards,  
    WLS Holdings AI Support Team

    """

    try:
        if not client:
            logger.error("Twilio client not initialized. Check your credentials.")
            return False

        content_variables = {
            "1": str(receiver_name),
            "2": str(application_no),
            "3": str(applicant_name),
            "4": str(leave_start_date),
            "5": str(leave_end_date),
            "6": str(leave_duration),
            "7": str(leave_type),
            "8": str(receiver_name),
            "9": str(application_no),
            "10": str(applicant_name),
            "11": str(leave_start_date),
            "12": str(leave_end_date),
            "13": str(leave_duration),
            "14": str(leave_type),
        }

        logger.info(f"Content variables: {content_variables}")

        # Run Twilio call in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        message = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                to=receiver_waba,
                messaging_service_sid=messaging_service_sid,
                content_sid=sick_leave_application_notification_id,
                content_variables=json.dumps(content_variables),
            ),
        )

        logger.info(f"WhatsApp leave application notification message sent successfully! SID: {message.sid}")
        logger.info(f"Message status: {message.status}")
        return message.status in ["accepted", "sent", "delivered"]

    except Exception as e:
        logger.error(
            f"Failed to send WhatsApp leave application notification message to {receiver_waba}: {str(e)}"
        )
        logger.error(f"Error type: {type(e).__name__}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return False



async def send_annual_leave_application_notification_message(
    receiver_name: str,
    application_no: str,
    applicant_name: str,
    leave_type: str, #annual leave
    leave_start_date: str,
    leave_end_date: str,
    leave_duration: str,
    receiver_waba: str,
    alert_message_en: Optional[str] = None,
    alert_message_zh: Optional[str] = None):

    """
    message template:


🚨 *Leave Notification*

Hello {{1}},

You’ve received a *Annual Leave Application Notification*. {{8}} Please check the details below.

🏷️ Application No.: *{{2}}*
👤 Applicant: *{{3}}*  
📅 Leave Period: *{{4}}* - *{{5}}*  ({{6}} days)
📝 Leave Type: *{{7}}*


Thank you!  

Best regards,  
WLS Holdings AI Support Team

--------------------------------

你好 {{9}}，

你已收到一則*年假申請通知*。{{16}}詳情如下：

🏷️ 申請編號：*{{10}}*
👤 申請人：*{{11}}*
📅 請假日期：*{{12}}* - *{{13}}*（共 *{{14}}* 日）
📝 假期類型：*{{15}}*

Best regards,  
WLS Holdings AI Support Team


⚠️ This application has been flagged as a policy violation because annual leave of more than two days must be submitted at least 14 days in advance.
⚠️ 此申請已被標記為違反公司政策，因為連續兩天以上的年假必須在開始日期前至少14天提交申請。

    """
    try:
        if not client:
            logger.error("Twilio client not initialized. Check your credentials.")
            return False

        content_variables = {
            "1": str(receiver_name),
            "2": str(application_no),
            "3": str(applicant_name),
            "4": str(leave_start_date),
            "5": str(leave_end_date),
            "6": str(leave_duration),
            "7": str(leave_type),
            "8": str(alert_message_en) if alert_message_en else "",
            "9": str(receiver_name),
            "10": str(application_no),
            "11": str(applicant_name),
            "12": str(leave_start_date),
            "13": str(leave_end_date),
            "14": str(leave_duration),
            "15": str(leave_type),
            "16": str(alert_message_zh) if alert_message_zh else "",
        }

        logger.info(f"Content variables: {content_variables}")

        # Run Twilio call in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        message = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                to=receiver_waba,
                messaging_service_sid=messaging_service_sid,
                content_sid=annual_leave_application_notification_id,
                content_variables=json.dumps(content_variables),
            ),
        )

        logger.info(f"WhatsApp leave application notification message sent successfully! SID: {message.sid}")
        logger.info(f"Message status: {message.status}")
        return message.status in ["accepted", "sent", "delivered"]

    except Exception as e:
        logger.error(
            f"Failed to send WhatsApp leave application notification message to {receiver_waba}: {str(e)}"
        )
        logger.error(f"Error type: {type(e).__name__}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

