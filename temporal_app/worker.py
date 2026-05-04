"""
Temporal Worker Configuration
The worker runs workflows and activities
"""

import asyncio
import logging
import os

from temporalio.worker import Worker

# Image processing activities are also causing issues with Temporal sandbox restrictions
from temporal_app.activities.image_processing_activities import (
    check_image_collection_activity, process_collected_images_activity)
# Import all activities
from temporal_app.activities.reminder_activities import (
    generate_project_reminder_summary_pdf, generate_reminder_summary_pdf,
    get_reminder_summary_info, process_task_reminders, retry_failed_reminders)
from temporal_app.client import get_temporal_client
# Image processing workflows are also causing issues with Temporal sandbox restrictions
from temporal_app.workflows.image_processing_workflows import (
    ImageCollectionWorkflow, ImageProcessingWorkflow)
from temporal_app.workflows.reminder_workflows import (
    ComprehensiveReminderWorkflow, FailedReminderRetryWorkflow,
    PdfGenerationWorkflow, ProjectReminderSummaryWorkflow,
    ReminderProcessingWorkflow, ScheduledReminderWorkflow)

TASK_QUEUE_NAME = os.getenv("TEMPORAL_TASK_QUEUE_NAME")

logger = logging.getLogger(__name__)


async def create_worker() -> Worker:
    """
    Create and configure the Temporal worker
    """
    # Get Temporal client
    client = await get_temporal_client()

    # Create worker
    worker = Worker(
        client=client,
        task_queue=TASK_QUEUE_NAME,
        workflows=[
            ReminderProcessingWorkflow,
            FailedReminderRetryWorkflow,
            PdfGenerationWorkflow,
            ProjectReminderSummaryWorkflow,
            ScheduledReminderWorkflow,
            ComprehensiveReminderWorkflow,
            DailyWeatherWorkflow,  # Weather workflow
            ImageCollectionWorkflow,
            ImageProcessingWorkflow,
        ],
        activities=[
            process_task_reminders,
            retry_failed_reminders,
            generate_reminder_summary_pdf,
            get_reminder_summary_info,
            generate_project_reminder_summary_pdf,
            send_local_weather_notifications_activity,  # Weather activity
            send_tomorrow_weather_notifications_activity,  # Weather activity
            process_collected_images_activity,
            check_image_collection_activity,
        ],
    )

    logger.info(f"Created Temporal worker for task queue: {TASK_QUEUE_NAME}")
    return worker


async def run_worker():
    """
    Run the Temporal worker
    """
    try:
        # Create worker
        worker = await create_worker()

        # Start worker
        logger.info("Starting Temporal worker...")
        await worker.run()

    except Exception as e:
        logger.error(f"Error running Temporal worker: {str(e)}")
        raise


if __name__ == "__main__":
    # Run the worker
    asyncio.run(run_worker())
