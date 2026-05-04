import os
import logging
import json
from dotenv import load_dotenv
from twilio.rest import Client
from typing import List, Dict


load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("defect_templates")

ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")
MESSAGING_SERVICE_SID = os.getenv("MESSAGING_SERVICE_SID")

client = Client(ACCOUNT_SID, AUTH_TOKEN) if ACCOUNT_SID and AUTH_TOKEN else None

SPECIAL_WORK_APPLICATION_ID = os.getenv("SPECIAL_WORK_APPLICATION_ID")
async def send_special_work_application_to_approvers(
                                             list_of_approvers = List[Dict[str, str]], 
                                             application_no = str,
                                             project_title = str, 
                                             applicant_name = str,
                                             attendance_images = List[str]):
    """
message template:
    
Hello {{1}},

You’ve received a *Special Work Application* for your review.  

🏷️ Application No.: *{{2}}*
🏗️ Project: *{{3}}*  
👤 Applicant: *{{4}}*  
📸 Attendance Images: *{{5}}*  

Please review the details above and confirm whether to approve or reject the application.  

Thank you!  

Best regards,  
ERP AI Support Team

    """
    # Format attendance images into a single readable string
    list_of_attendance_images = "\n".join(
        [f"{index + 1}. {attendance_image}" for index, attendance_image in enumerate(attendance_images)]
    )
    try:
        for approver in list_of_approvers:
            approver_name = approver["name"]
            approver_waba = approver["waba"]
            logging.info(f"Sending special work application to approvers to {approver_name} ({approver_waba})")
            content_sid = SPECIAL_WORK_APPLICATION_ID

            content_variables = {
                "1": str(approver_name),
                "2": str(application_no),
                "3": str(project_title),
                "4": str(applicant_name),
                "5": list_of_attendance_images
            }

            message = client.messages.create(
            from_=f"whatsapp:{WHATSAPP_NUMBER}",
            to=approver_waba,
            messaging_service_sid=MESSAGING_SERVICE_SID,
            content_sid=content_sid,
            content_variables=json.dumps(content_variables)
            )
            logger.info(f"Special work application to approvers sent successfully to {approver_name} ({approver_waba}), SID: {message.sid}")
            return True
        return True
    except Exception as e:
        logger.error(f"Failed to send special work application to approvers to {approver_waba}: {str(e)}")
        return False









SPECIAL_WORK_NOTIFICATION_ID = os.getenv("SPECIAL_WORK_NOTIFICATION_ID")
async def send_special_work_notification_to_receivers(list_of_receivers, 
                                             application_no,
                                             project_title, 
                                             applicant_name,
                                             attendance_images):
    """
    message template:
    
Hello {{1}},

You’ve received a *Special Work Notification*.  Please check the details below.

🏷️ Application No.: *{{2}}*
🏗️ Project: *{{3}}*  
👤 Applicant: *{{4}}*  
📸 Attendance Images: *{{5}}*  

Thank you!  

Best regards,  
ERP AI Support Team

    """

    try:
        for receiver in list_of_receivers:
            receiver_name = receiver.name
            receiver_waba = receiver.waba
            content_sid = SPECIAL_WORK_NOTIFICATION_ID
            content_variables = {
                "1": str(receiver_name),
                "2": str(application_no),
                "3": str(project_title),
                "4": str(applicant_name),
                "5": str(attendance_images)
            }
            
            message = client.messages.create(
                from_=f"whatsapp:{WHATSAPP_NUMBER}",
                to=receiver_waba,
                messaging_service_sid=MESSAGING_SERVICE_SID,
                content_sid=content_sid,
                content_variables=json.dumps(content_variables)
            )
            logger.info(f"Special work notification to receivers sent successfully to {receiver_name} ({receiver_waba}), SID: {message.sid}")
            return True
        return True
    except Exception as e:
        logger.error(f"Failed to send special work notification to receivers to {receiver_waba}: {str(e)}")
        return False


