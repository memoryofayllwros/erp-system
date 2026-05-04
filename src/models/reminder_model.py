import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
import pytz
from beanie import Document
from pydantic import Field

base_url = os.getenv("BASE_URL")


from src.pdf_templates.reminder_summary_pdf import \
    generate_reminder_summary_pdf
from src.utils.datetime_standarization_helpers import get_this_moment, HK_TZ
logger = logging.getLogger(__name__)


async def migrate_reminders(reminder_date: date, reminder_time: str) -> datetime:
    # Handle both HH:MM and HH:MM:SS formats
    try:
        if reminder_time.count(":") == 2:
            # HH:MM:SS format
            time_obj = datetime.strptime(reminder_time, "%H:%M:%S").time()
        else:
            # HH:MM format
            time_obj = datetime.strptime(reminder_time, "%H:%M").time()
    except ValueError as e:
        raise ValueError(
            f"Invalid time format '{reminder_time}'. Expected HH:MM or HH:MM:SS format."
        )

    hk_datetime = datetime.combine(reminder_date, time_obj)  # in HK timezone

    return hk_datetime  # in HK timezone


class Reminder(Document):
    project_code: str
    task_name: Optional[str] = None
    reminder_type: Optional[str] = None
    reminder_description: str
    reminder_datetime: datetime  # in HK timezone
    user_waba: str  # Store the users WhatsApp number
    name: str  # Store the user's name
    sent: bool = Field(default=False)  # Track if reminder has been sent
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "reminder_collection"

    class Config:
        arbitrary_types_allowed = True

    @property
    def reminder_datetime_hkt(self) -> datetime:
        """Get reminder datetime in HKT for display"""
        return self.reminder_datetime.astimezone(HK_TZ)

    @classmethod
    async def add_reminder_function(
        cls,
        project_code: str,
        reminder_description: str,
        reminder_date: date,
        reminder_time: str,
        user_waba: str,
        name: str,
    ) -> dict:
        try:
            logger.info(f"Adding new reminder for project {project_code}")

            # Get project details to validate dates
            from src.models.project_model import Project

            project = await Project.find_one(
                Project.project_code == project_code, Project.deleted_at == None
            )
            if not project:
                raise ValueError(f"No project found with project_code: {project_code}")

            reminder_datetime_combined_hk = await migrate_reminders(
                reminder_date, reminder_time
            )

            if (
                project.start_date
                and reminder_datetime_combined_hk.date() < project.start_date
            ):
                raise ValueError(
                    f"Task start date ({reminder_datetime_combined_hk.date()}) cannot be before project start date ({project.start_date})"
                )
            if (
                project.end_date
                and reminder_datetime_combined_hk.date() > project.end_date
            ):
                raise ValueError(
                    f"Task end date ({reminder_datetime_combined_hk.date()}) cannot be after project end date ({project.end_date})"
                )

            new_reminder = cls(
                project_code=project_code,
                reminder_description=reminder_description,
                reminder_datetime=reminder_datetime_combined_hk,  # in HK timezone
                user_waba=user_waba,
                name=name,
                sent=False,
                created_at=get_this_moment()
            )

            await new_reminder.insert()
            logger.info(f"Successfully added reminder for project {project_code}")

            # Trigger reminder summary PDF generation asynchronously using Temporal (force regenerate to include new reminder)
            try:
                from temporal_app.services.reminder_service import \
                    temporal_reminder_service

                workflow_id = (
                    await temporal_reminder_service.trigger_reminder_summary_generation(
                        project_code, force_regenerate=True
                    )
                )
                logger.info(
                    f"Triggered Temporal workflow for reminder summary PDF generation for project {project_code}, workflow ID: {workflow_id}"
                )

            except Exception as pdf_error:
                # Log error but don't fail the reminder creation
                logger.warning(
                    f"Failed to trigger Temporal workflow for reminder summary PDF generation for project {project_code}: {str(pdf_error)}"
                )

                # Try direct fallback using the service
                try:
                    logger.info(
                        f"Attempting direct PDF generation fallback for project {project_code}"
                    )
                    from temporal_app.notifications.reminder_summary_service import \
                        reminder_summary_service

                    fallback_result = (
                        await reminder_summary_service.generate_reminder_summary_pdf(
                            project_code, True
                        )
                    )
                    logger.info(
                        f"Direct fallback generation completed for project {project_code}: {fallback_result.get('status')}"
                    )
                except Exception as direct_fallback_error:
                    logger.error(
                        f"Direct fallback PDF generation also failed for project {project_code}: {str(direct_fallback_error)}"
                    )

            message = f"✅ 成功新增提醒！\n項目編號: {project_code}\n📝 任務描述: {reminder_description}\n⏰ 提醒時間: {reminder_date} {reminder_time}"

            return {
                "status": "success",
                "message": message,
                "new_reminder": {
                    "reminder_id": str(new_reminder.id),
                    "project_code": new_reminder.project_code,
                    "reminder_description": new_reminder.reminder_description,
                    "reminder_datetime": new_reminder.reminder_datetime,
                },
            }

        except Exception as e:
            error_message = f"⚠️ {str(e)}"
            logger.error(f"Error adding reminder for project {project_code}: {str(e)}")
            return {"status": "error", "message": error_message}

    @classmethod
    async def get_project_reminders(cls, project_code: str) -> list:
        try:
            logger.info(f"Fetching reminders for project {project_code}")

            reminders = await cls.find(
                cls.project_code == project_code, cls.deleted_at == None
            ).to_list()

            logger.info(f"Found {len(reminders)} reminders for project {project_code}")

            return [
                {
                    "reminder_id": str(reminder.id),
                    "project_code": reminder.project_code,
                    "reminder_description": reminder.reminder_description,
                    "reminder_datetime": reminder.reminder_datetime,
                    "name": reminder.name,
                    "user_waba": reminder.user_waba,
                }
                for reminder in reminders
            ]

        except Exception as e:
            logger.error(
                f"Error fetching reminders for project {project_code}: {str(e)}"
            )
            return []

    @classmethod
    async def update_reminder_sent_status(cls, reminder_id: str, sent: bool) -> bool:
        try:
            reminder = await cls.find_one(cls.id == reminder_id, cls.deleted_at == None)
            if not reminder:
                return False
            reminder.sent = sent
            await reminder.save()
            return True
        except Exception as e:
            logger.error(f"Error updating reminder sent status: {str(e)}")
            return False

    @classmethod
    async def generate_reminder_summary_pdf_from_project_code(
        cls, project_code: str
    ) -> Dict[str, Any]:
        """Generate reminder summary PDF for a project"""
        try:
            # Get project information
            from src.models.project_model import Project

            project_info = await Project.find_one(
                Project.project_code == project_code, Project.deleted_at == None
            )
            if not project_info:
                return {
                    "status": "error",
                    "message": f"Project {project_code} not found",
                }

            reminders = await cls.get_project_reminders(project_code)

            pdf_content = await generate_reminder_summary_pdf(project_info, reminders)

            reminder_summary_filename = f"reminder_summary_{project_code}_{get_this_moment().strftime('%Y%m%d_%H%M%S')}.pdf"

            from infrastructure.database.database_connection import get_grid_fs

            # Get GridFS connection (will create if needed)
            grid_fs = await get_grid_fs()

            reminder_summary_id = await grid_fs.upload_from_stream(
                filename=reminder_summary_filename, source=pdf_content
            )

            reminder_summary_id_str = str(reminder_summary_id)
            logger.info(f"Reminder summary ID: {reminder_summary_id_str}")
            await Project.update_reminder_summary_id(
                project_code, reminder_summary_id_str
            )

            if os.path.exists(pdf_content):
                try:
                    os.remove(pdf_content)
                    logger.info(
                        f"Cleaned up temporary file {pdf_content} after failed upload"
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to clean up temporary file {pdf_content}: {cleanup_error}"
                    )

            return {
                "status": "success",
                "message": f"Reminder summary PDF generated successfully for project {project_code}",
                "reminder_summary_id": reminder_summary_id_str,
                "filename": reminder_summary_filename,
                "download_url": f"{base_url}/reminder-summary/{reminder_summary_id_str}.pdf",
            }

        except Exception as e:
            logger.error(
                f"Error generating reminder summary PDF for project {project_code}: {str(e)}"
            )
            return {
                "status": "error",
                "message": f"Error generating reminder summary PDF: {str(e)}",
            }
