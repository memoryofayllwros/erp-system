"""
Temporal Activities for Reminder Management
Activities are the building blocks that do the actual work
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from pytz import timezone as pytz_timezone
from temporalio import activity
from src.utils.datetime_standarization_helpers import get_this_moment
logger = logging.getLogger(__name__)
HKT_TIMEZONE = pytz_timezone("Asia/Hong_Kong")


@activity.defn
async def process_task_reminders() -> Dict[str, Any]:
    try:
        activity.logger.info("Starting task reminder processing...")

        # Initialize database connection
        from infrastructure.database.database_connection import init

        await init()

        # Import and use service
        from temporal_app.notifications.task_notification import \
            TaskNotificationService

        task_notification_service = TaskNotificationService()
        result = await task_notification_service.process_reminders()

        return {
            "status": "success",
            "processed": result.get("sent_count", 0),
            "found": result.get("total_found", 0),
            "time": get_this_moment().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }

    except Exception as e:
        activity.logger.error(f"Error in process_task_reminders: {str(e)}")
        raise


@activity.defn
async def retry_failed_reminders() -> Dict[str, Any]:

    try:
        activity.logger.info("Starting failed reminder retry processing...")

        # Initialize database connection
        from infrastructure.database.database_connection import init

        await init()

        # Import and use service
        from temporal_app.notifications.task_notification import \
            TaskNotificationService

        task_notification_service = TaskNotificationService()
        result = await task_notification_service.retry_failed_reminders()

        return {
            "status": "success",
            "retried": result.get("retried_count", 0),
            "time": get_this_moment().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }

    except Exception as e:
        activity.logger.error(f"Error in retry_failed_reminders: {str(e)}")
        raise


@activity.defn
async def generate_project_reminder_summary_pdf(
    project_code: str, force_regenerate: bool = False
) -> Dict[str, Any]:
    """
    Activity to generate reminder summary PDF for a specific project
    """
    try:
        activity.logger.info(
            f"Starting PDF generation for project {project_code} (force_regenerate: {force_regenerate})"
        )

        # Use the existing service method
        from temporal_app.notifications.reminder_summary_service import \
            ReminderSummaryService

        service = ReminderSummaryService()
        result = await service.generate_reminder_summary_pdf(
            project_code, force_regenerate
        )

        activity.logger.info(
            f"PDF generation completed for project {project_code}: {result.get('status')}"
        )
        return result

    except Exception as e:
        activity.logger.error(
            f"PDF generation failed for project {project_code}: {str(e)}"
        )
        return {"status": "error", "message": str(e), "project_code": project_code}


@activity.defn
async def generate_reminder_summary_pdf(
    client_id: str, start_date: str, end_date: str, include_completed: bool = False
) -> Dict[str, Any]:
    """
    Activity to generate reminder summary PDF
    """
    try:
        activity.logger.info(f"Starting PDF generation for client {client_id}")

        # Initialize database connection
        from infrastructure.database.database_connection import init

        await init()

        # Import and use service
        from temporal_app.notifications.reminder_summary_service import \
            ReminderSummaryService

        service = ReminderSummaryService()
        result = await service.generate_reminder_summary_pdf(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            include_completed=include_completed,
        )

        return {
            "status": "success",
            "file_id": result.get("file_id"),
            "filename": result.get("filename"),
            "client_id": client_id,
            "time": get_this_moment().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }

    except Exception as e:
        activity.logger.error(f"Error in generate_reminder_summary_pdf: {str(e)}")
        raise


@activity.defn
async def get_reminder_summary_info(
    client_id: str, start_date: str, end_date: str, include_completed: bool = False
) -> Dict[str, Any]:
    """
    Activity to get reminder summary information
    """
    try:
        activity.logger.info(f"Getting reminder summary info for client {client_id}")

        # Initialize database connection
        from infrastructure.database.database_connection import init

        await init()

        # Import and use service
        from temporal_app.notifications.reminder_summary_service import \
            ReminderSummaryService

        service = ReminderSummaryService()
        result = await service.get_reminder_summary_info(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            include_completed=include_completed,
        )

        return {
            "status": "success",
            "summary": result,
            "client_id": client_id,
            "time": get_this_moment().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }

    except Exception as e:
        activity.logger.error(f"Error in get_reminder_summary_info: {str(e)}")
        raise
