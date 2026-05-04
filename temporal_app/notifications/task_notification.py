import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from twilio.rest import Client

from src.models.reminder_model import Reminder
from src.utils.datetime_standarization_helpers import get_this_moment
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")
waba = os.getenv("WHATSAPP_NUMBER")
messaging_service_sid = os.getenv("MESSAGING_SERVICE_SID")

client = Client(account_sid, auth_token) if account_sid and auth_token else None

task_reminder_id = "HX5064816f6663b75fd5017bb2562d200e"


async def send_task_reminder_message(
    name, reminder_description, project_code, whatsapp_number
):
    """
    Send a task reminder message via WhatsApp using Twilio
    """
    try:
        if not client:
            logger.error("Twilio client not initialized. Check your credentials.")
            return False

        content_variables = {
            "1": str(name),
            "2": str(reminder_description),
            "3": str(project_code),
            "4": str(name),
            "5": str(reminder_description),
            "6": str(project_code),
        }

        logger.info(f"Content variables: {content_variables}")

        # Run Twilio call in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        message = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                to=whatsapp_number,
                messaging_service_sid=messaging_service_sid,
                content_sid=task_reminder_id,
                content_variables=json.dumps(content_variables),
            ),
        )

        logger.info(f"WhatsApp reminder message sent successfully! SID: {message.sid}")
        logger.info(f"Message status: {message.status}")
        return message.status in ["accepted", "sent", "delivered"]

    except Exception as e:
        logger.error(
            f"Failed to send WhatsApp reminder message to {whatsapp_number}: {str(e)}"
        )
        logger.error(f"Error type: {type(e).__name__}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


class TaskNotificationService:
    """
    Service for sending task reminder notifications via WhatsApp
    """

    def __init__(self):
        self.client = client
        self.logger = logger

    async def send_task_reminder(
        self,
        name: str,
        reminder_description: str,
        project_code: str,
        whatsapp_number: str,
    ) -> bool:
        """
        Send a task reminder notification

        Args:
            name: Name of the person to notify
            reminder_description: Description of the reminder
            project_code: Project number
            whatsapp_number: WhatsApp number to send to

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        return await send_task_reminder_message(
            name, reminder_description, project_code, whatsapp_number
        )

    async def send_bulk_reminders(self, reminders_data: list) -> dict:
        """
        Send multiple reminder notifications

        Args:
            reminders_data: List of reminder data dictionaries

        Returns:
            dict: Results summary with success/failure counts
        """
        results = {
            "total": len(reminders_data),
            "success": 0,
            "failed": 0,
            "failures": [],
        }

        for reminder_data in reminders_data:
            try:
                success = await self.send_task_reminder(
                    reminder_data["name"],
                    reminder_data["description"],
                    reminder_data["project_code"],
                    reminder_data["whatsapp_number"],
                )

                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["failures"].append(
                        {
                            "project_code": reminder_data["project_code"],
                            "reason": "Message sending failed",
                        }
                    )

            except Exception as e:
                results["failed"] += 1
                results["failures"].append(
                    {
                        "project_code": reminder_data.get("project_code", "unknown"),
                        "reason": str(e),
                    }
                )
                self.logger.error(
                    f"Failed to send reminder for project {reminder_data.get('project_code')}: {e}"
                )

        return results

    async def retry_failed_reminders(self) -> dict:
        """
        Retry sending failed reminder notifications

        This function finds reminders that:
        1. Are past their scheduled time
        2. Have not been sent successfully
        3. Were attempted but failed (we'll identify these by time logic)

        Returns:
            dict: Results summary with retry counts
        """
        try:
            # Find reminders that are overdue (past their scheduled time) but not yet sent
            from datetime import datetime, timedelta
            from src.utils.datetime_standarization_helpers import get_this_moment   
            # Consider reminders that are more than 5 minutes overdue as "failed attempts"
            current_time_hk = get_this_moment() # in HK timezone
            retry_threshold = current_time_hk - timedelta(minutes=5)

            self.logger.info(f"Looking for failed reminders before: {retry_threshold}")

            # Find reminders that should have been sent but weren't
            failed_reminders = await Reminder.find(
                Reminder.sent == False,
                Reminder.reminder_datetime
                <= retry_threshold,  # More than 5 minutes overdue
                Reminder.deleted_at == None,
            ).to_list()

            total_to_retry = len(failed_reminders)
            self.logger.info(f"Found {total_to_retry} failed reminders to retry")

            if total_to_retry == 0:
                return {
                    "total_retried": 0,
                    "success": 0,
                    "failed": 0,
                    "message": "No failed reminders found to retry",
                }

            retried_count = 0
            success_count = 0
            failed_count = 0
            retry_details = []

            for reminder in failed_reminders:
                try:
                    self.logger.info(
                        f"Retrying failed reminder for project {reminder.project_code} - {reminder.reminder_description}"
                    )

                    # Attempt to send the reminder again
                    success = await self.send_task_reminder(
                        name=reminder.name,
                        reminder_description=reminder.reminder_description,
                        project_code=reminder.project_code,
                        whatsapp_number=reminder.whatsapp_number,
                    )

                    retried_count += 1

                    if success:
                        # Mark as sent
                        reminder.sent = True
                        await reminder.save()
                        success_count += 1
                        self.logger.info(
                            f"Successfully retried reminder for project {reminder.project_code}"
                        )

                        retry_details.append(
                            {
                                "project_code": reminder.project_code,
                                "status": "success",
                                "reminder_id": str(reminder.id),
                                "message": "Retry successful",
                            }
                        )
                    else:
                        failed_count += 1
                        self.logger.error(
                            f"Retry failed for reminder project {reminder.project_code}"
                        )

                        retry_details.append(
                            {
                                "project_code": reminder.project_code,
                                "status": "failed",
                                "reminder_id": str(reminder.id),
                                "message": "Retry failed - WhatsApp message sending failed",
                            }
                        )

                except Exception as e:
                    retried_count += 1
                    failed_count += 1
                    self.logger.error(
                        f"Exception during retry for project {reminder.project_code}: {e}"
                    )

                    retry_details.append(
                        {
                            "project_code": reminder.project_code,
                            "status": "error",
                            "reminder_id": (
                                str(reminder.id)
                                if hasattr(reminder, "id")
                                else "unknown"
                            ),
                            "message": f"Exception during retry: {str(e)}",
                        }
                    )

            result = {
                "total_found": total_to_retry,
                "total_retried": retried_count,
                "success": success_count,
                "failed": failed_count,
                "success_rate": (
                    f"{(success_count/retried_count)*100:.1f}%"
                    if retried_count > 0
                    else "0%"
                ),
                "retry_details": retry_details,
                "processed_at": get_this_moment().isoformat(),
            }

            self.logger.info(
                f"Retry failed reminders completed: {success_count} successful, {failed_count} failed out of {retried_count} retried"
            )
            return result

        except Exception as e:
            self.logger.error(f"Error in retry_failed_reminders: {e}")
            return {
                "total_retried": 0,
                "success": 0,
                "failed": 1,
                "error": str(e),
                "message": f"Error during retry process: {str(e)}",
                "processed_at": get_this_moment().isoformat(),
            }

    async def process_reminders(self) -> dict:
        """
        Process all pending reminders that are due to be sent

        Fetches reminders from database where:
        - sent = False
        - reminder_datetime <= current time (HK timezone)
        - deleted_at is None

        Sends WhatsApp notifications and updates sent status

        Returns:
            dict: Results summary with counts and details
        """
        try:
            # Use UTC timezone-aware datetime for consistency
            current_time_hk = get_this_moment() # in HK timezone
            self.logger.info(f"Processing reminders due before: {current_time_hk}")

            # Fetch all unsent reminders that are due
            due_reminders = await Reminder.find(
                Reminder.sent == False,
                Reminder.reminder_datetime <= current_time_hk,
                Reminder.deleted_at == None,
            ).to_list()

            total_found = len(due_reminders)
            self.logger.info(f"Found {total_found} due reminders to process")

            if total_found == 0:
                return {
                    "total_found": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "message": "No due reminders found",
                }

            sent_count = 0
            failed_count = 0
            failed_details = []

            for reminder in due_reminders:
                try:
                    self.logger.info(
                        f"Processing reminder for project {reminder.project_code} - {reminder.reminder_description}"
                    )

                    # Send the WhatsApp notification
                    success = await self.send_task_reminder(
                        name=reminder.name,
                        reminder_description=reminder.reminder_description,
                        project_code=reminder.project_code,
                        whatsapp_number=reminder.whatsapp_number,
                    )

                    if success:
                        # Mark as sent
                        reminder.sent = True
                        await reminder.save()
                        sent_count += 1
                        self.logger.info(
                            f"Successfully sent reminder for project {reminder.project_code}"
                        )
                    else:
                        failed_count += 1
                        failed_details.append(
                            {
                                "project_code": reminder.project_code,
                                "reason": "WhatsApp message sending failed",
                                "reminder_id": str(reminder.id),
                            }
                        )
                        self.logger.error(
                            f"Failed to send reminder for project {reminder.project_code}"
                        )

                except Exception as e:
                    failed_count += 1
                    failed_details.append(
                        {
                            "project_code": reminder.project_code,
                            "reason": str(e),
                            "reminder_id": (
                                str(reminder.id)
                                if hasattr(reminder, "id")
                                else "unknown"
                            ),
                        }
                    )
                    self.logger.error(
                        f"Exception processing reminder for project {reminder.project_code}: {e}"
                    )

            result = {
                "total_found": total_found,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "success_rate": (
                    f"{(sent_count/total_found)*100:.1f}%" if total_found > 0 else "0%"
                ),
                "processed_at": get_this_moment().isoformat(),
            }

            if failed_details:
                result["failed_details"] = failed_details

            self.logger.info(
                f"Reminder processing completed: {sent_count} sent, {failed_count} failed out of {total_found} total"
            )
            return result

        except Exception as e:
            self.logger.error(f"Error in process_reminders: {e}")
            return {
                "total_found": 0,
                "sent_count": 0,
                "failed_count": 1,
                "error": str(e),
                "processed_at": get_this_moment().isoformat(),
            }
