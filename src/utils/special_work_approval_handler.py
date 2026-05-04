import logging
import re
from typing import Optional, Dict, Any
from src.models.application_and_approval_model import ApplicationAndApproval, ApplicationStatus
from src.models.user_model import User
from src.message_templates.message_response_templates import send_whatsapp_message_back
from bson import ObjectId


class SpecialWorkApprovalHandler:
    """Handles approval/rejection responses for special work applications"""
    
    @staticmethod
    def is_approval_response(message: str) -> bool:
        """Check if message contains approval keywords"""
        approval_keywords = [
            "approve", "approved", "approval", "yes", "ok", "okay", "confirm", "confirmed",
            "批准", "同意", "確認", "可以", "好", "得", "係", "是", "對", "正確", "冇問題"
        ]
        
        message_lower = message.lower().strip()
        return any(keyword in message_lower for keyword in approval_keywords)
    
    @staticmethod
    def is_rejection_response(message: str) -> bool:
        """Check if message contains rejection keywords"""
        rejection_keywords = [
            "reject", "rejected", "rejection", "no", "deny", "denied", "cancel", "cancelled",
            "拒絕", "不同意", "取消", "唔得", "唔係", "否", "錯", "唔啱", "唔可以"
        ]
        
        message_lower = message.lower().strip()
        return any(keyword in message_lower for keyword in rejection_keywords)
    
    @staticmethod
    def extract_application_number(message: str) -> Optional[str]:
        """Extract application number from message (format: ERP-YYYYMMDDHHMMSS)"""
        pattern = r'ERP-\d{14}'
        match = re.search(pattern, message)
        return match.group(0) if match else None
    
    @staticmethod
    async def find_approver_by_whatsapp_number(whatsapp_number: str) -> Optional[User]:
        """Find approver user by WhatsApp number"""
        try:
            # Extract country code and mobile number from WhatsApp format
            # Format: whatsapp:+85212345678
            if whatsapp_number.startswith("whatsapp:+"):
                phone_number = whatsapp_number[9:]  # Remove "whatsapp:+"
                country_code = phone_number[:3]  # Assume 3-digit country code
                mobile = phone_number[3:]
                
                # Find user by country code and mobile
                user = await User.find_one(
                    User.country_code == country_code,
                    User.mobile == mobile,
                    User.deleted_at == None
                )
                return user
        except Exception as e:
            logging.error(f"Error finding approver by WhatsApp number: {str(e)}")
        return None
    
    @staticmethod
    async def handle_approval_response(sender: str, message: str) -> bool:
        """Handle approval response from approver"""
        try:
            # Extract application number
            application_no = SpecialWorkApprovalHandler.extract_application_number(message)
            if not application_no:
                logging.warning(f"No application number found in approval message from {sender}")
                return False
            
            # Find the application
            application = await ApplicationAndApproval.find_by_application_no(application_no)
            if not application:
                logging.warning(f"Application not found: {application_no}")
                return False
            
            # Check if application is still pending
            if application.approval_status is not None and len(application.approval_status) > 0:
                logging.warning(f"Application {application_no} is not pending, already has approval status")
                return False
            
            # Find the approver
            approver = await SpecialWorkApprovalHandler.find_approver_by_whatsapp_number(sender)
            if not approver:
                logging.warning(f"Approver not found for WhatsApp number: {sender}")
                return False
            
            # Check if this user is authorized to approve this application
            if str(approver.id) not in application.approvers:
                logging.warning(f"User {approver.id} is not authorized to approve application {application_no}")
                return False
            
            # Approve the application
            success = await application.approve(approver_id=str(approver.id), approval_status=ApplicationStatus.APPROVED)
            if not success:
                logging.error(f"Failed to approve application {application_no}")
                return False
            
            # Send confirmation to approver
            try:
                confirmation_message = f"✅ 申請已批准\n\n申請編號: {application_no}\n\n已成功處理簽到記錄。\n\n✅ Application Approved\n\nApplication No.: {application_no}\n\nAttendance record processed successfully."
                await send_whatsapp_message_back(confirmation_message, sender)
                logging.info(f"Approval confirmation sent to {sender}")
            except Exception as e:
                logging.error(f"Failed to send approval confirmation: {str(e)}")
            
            # Send notification to applicant
            try:
                # Find the applicant
                applicant = await User.find_one(User.id == ObjectId(application.user_id), User.deleted_at == None)
                if applicant:
                    applicant_waba = f"whatsapp:+{applicant.country_code}{applicant.mobile}"
                    notification_message = f"✅ 您的特殊工作申請已獲批准\n\n申請編號: {application_no}\n\n簽到記錄已成功處理。\n\n✅ Your special work application has been approved\n\nApplication No.: {application_no}\n\nAttendance record processed successfully."
                    await send_whatsapp_message_back(notification_message, applicant_waba)
                    logging.info(f"Approval notification sent to applicant {applicant_waba}")
            except Exception as e:
                logging.error(f"Failed to send approval notification to applicant: {str(e)}")
            
            logging.info(f"Successfully processed approval for application {application_no}")
            return True
            
        except Exception as e:
            logging.error(f"Error handling approval response: {str(e)}")
            return False
    
    @staticmethod
    async def handle_rejection_response(sender: str, message: str) -> bool:
        """Handle rejection response from approver"""
        try:
            # Extract application number
            application_no = SpecialWorkApprovalHandler.extract_application_number(message)
            if not application_no:
                logging.warning(f"No application number found in rejection message from {sender}")
                return False
            
            # Find the application
            application = await ApplicationAndApproval.find_by_application_no(application_no)
            if not application:
                logging.warning(f"Application not found: {application_no}")
                return False
            
            # Check if application is still pending
            if application.approval_status is not None and len(application.approval_status) > 0:
                logging.warning(f"Application {application_no} is not pending, already has approval status")
                return False
            
            # Find the approver
            approver = await SpecialWorkApprovalHandler.find_approver_by_whatsapp_number(sender)
            if not approver:
                logging.warning(f"Approver not found for WhatsApp number: {sender}")
                return False
            
            # Check if this user is authorized to reject this application
            if str(approver.id) not in application.approvers:
                logging.warning(f"User {approver.id} is not authorized to reject application {application_no}")
                return False
            
            # Reject the application
            success = await application.reject(approver_id=str(approver.id), approval_status=ApplicationStatus.REJECTED)
            if not success:
                logging.error(f"Failed to reject application {application_no}")
                return False
            
            # Send confirmation to approver
            try:
                confirmation_message = f"❌ 申請已拒絕\n\n申請編號: {application_no}\n\n❌ Application Rejected\n\nApplication No.: {application_no}"
                await send_whatsapp_message_back(confirmation_message, sender)
                logging.info(f"Rejection confirmation sent to {sender}")
            except Exception as e:
                logging.error(f"Failed to send rejection confirmation: {str(e)}")
            
            # Send notification to applicant
            try:
                # Find the applicant
                applicant = await User.find_one(User.id == ObjectId(application.user_id), User.deleted_at == None)
                if applicant:
                    applicant_waba = f"whatsapp:+{applicant.country_code}{applicant.mobile}"
                    notification_message = f"❌ 您的特殊工作申請已被拒絕\n\n申請編號: {application_no}\n\n❌ Your special work application has been rejected\n\nApplication No.: {application_no}"
                    await send_whatsapp_message_back(notification_message, applicant_waba)
                    logging.info(f"Rejection notification sent to applicant {applicant_waba}")
            except Exception as e:
                logging.error(f"Failed to send rejection notification to applicant: {str(e)}")
            
            logging.info(f"Successfully processed rejection for application {application_no}")
            return True
            
        except Exception as e:
            logging.error(f"Error handling rejection response: {str(e)}")
            return False
    
    @staticmethod
    async def process_message(sender: str, message: str) -> bool:
        """Process incoming message to check if it's an approval/rejection response"""
        try:
            # Check if message contains application number
            application_no = SpecialWorkApprovalHandler.extract_application_number(message)
            if not application_no:
                return False  # Not an approval/rejection message
            
            # Check if it's an approval response
            if SpecialWorkApprovalHandler.is_approval_response(message):
                logging.info(f"Processing approval response from {sender} for application {application_no}")
                return await SpecialWorkApprovalHandler.handle_approval_response(sender, message)
            
            # Check if it's a rejection response
            elif SpecialWorkApprovalHandler.is_rejection_response(message):
                logging.info(f"Processing rejection response from {sender} for application {application_no}")
                return await SpecialWorkApprovalHandler.handle_rejection_response(sender, message)
            
            return False  # Not a valid approval/rejection message
            
        except Exception as e:
            logging.error(f"Error processing approval/rejection message: {str(e)}")
            return False
