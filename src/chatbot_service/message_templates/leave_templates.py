import os
import logging
import json
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("defect_templates")

ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")
MESSAGING_SERVICE_SID = os.getenv("MESSAGING_SERVICE_SID")

client = Client(ACCOUNT_SID, AUTH_TOKEN) if ACCOUNT_SID and AUTH_TOKEN else None

LEAVE_APPLICATION_ID = os.getenv("LEAVE_APPLICATION_ID")
async def send_leave_application_to_approvers(list_of_approvers,  
                                             application_no,
                                             applicant_name,
                                             leave_start_date,
                                             leave_end_date,
                                             leave_reason=None):
    """
message template:

Hello {{1}},

You've received a *Leave Application* for your review.

🏷️ Application No.: *{{2}}*
👤 Applicant: *{{3}}*  
📅 Leave Period: *{{4}}* - *{{5}}*  
📝 Reason: *{{6}}*

Please review the details above and confirm whether to approve or reject the application.

Thank you!

Best regards,  
ERP AI Support Team

"""


    try:
        for approver in list_of_approvers:
            approver_name = approver.name
            approver_waba = approver.waba
            content_sid = LEAVE_APPLICATION_ID
            
            content_variables = {
            "1": str(approver_name),
            "2": str(application_no),
            "3": str(applicant_name),
            "4": str(leave_start_date),
            "5": str(leave_end_date),
            "6": str(leave_reason)
            }
            content_variables = json.dumps(content_variables)

            message = client.messages.create(
            from_=f"whatsapp:{WHATSAPP_NUMBER}",
            to=approver_waba,
            messaging_service_sid=MESSAGING_SERVICE_SID,
            content_sid=content_sid,
            content_variables=json.dumps(content_variables)
        )
            logger.info(f"Leave application to approvers sent successfully to {approver_name} ({approver_waba}), SID: {message.sid}")
            return True
    except Exception as e:
        logger.error(f"Failed to send leave application to approvers to {approver_waba}: {str(e)}")
        return False





LEAVE_NOTIFICATION_ID = os.getenv("LEAVE_NOTIFICATION_ID")
async def send_leave_application_to_receivers(list_of_receivers, 
                                             application_no,
                                             applicant_name,
                                             leave_start_date,
                                             leave_end_date,
                                             leave_reason):
    """
    message template:
    
Hello {{1}},

You’ve received a *Leave Application Notification*.  Please check the details below.

🏷️ Application No.: *{{2}}*
👤 Applicant: *{{3}}*  
📅 Leave Period: *{{4}}* - *{{5}}*  
📝 Reason: *{{6}}*

Thank you!  

Best regards,  
ERP AI Support Team

    """

    try:
        for receiver in list_of_receivers:
            receiver_name = receiver.name
            receiver_waba = receiver.waba
            content_sid = LEAVE_NOTIFICATION_ID
            if not content_sid:
                logger.error("No content SID configured for leave application")
                return None
            
            content_variables = {
                "1": str(receiver_name),
                "2": str(application_no),
                "3": str(applicant_name),
                "4": str(leave_start_date),
                "5": str(leave_end_date),
                "6": str(leave_reason)
            }
            
            message = client.messages.create(
                from_=f"whatsapp:{WHATSAPP_NUMBER}",
                to=receiver_waba,
                messaging_service_sid=MESSAGING_SERVICE_SID,
                content_sid=content_sid,
                content_variables=json.dumps(content_variables)
            )
            logger.info(f"Leave application to receivers sent successfully to {receiver_name} ({receiver_waba}), SID: {message.sid}")
            return True
        return True
    except Exception as e:
        logger.error(f"Failed to send leave application to receivers to {receiver_waba}: {str(e)}")
        return False


