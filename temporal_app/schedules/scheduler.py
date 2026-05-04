import asyncio
import logging
from datetime import datetime, timedelta

from temporalio.client import (ScheduleActionStartWorkflow,
                               ScheduleIntervalSpec, ScheduleSpec)
from temporalio.common import RetryPolicy

from temporal_app.client import get_temporal_client
from temporal_app.workflows.attendance_workflows import \
    AttendancePDFUpdateWorkflow
from temporal_app.workflows.reminder_workflows import (
    FailedReminderRetryWorkflow, ReminderProcessingWorkflow)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
from src.utils.datetime_standarization_helpers import get_this_moment
from temporal_app.worker import TASK_QUEUE_NAME


class TemporalScheduler:

    def __init__(self):
        self.client = None
        self.schedules = {}

    async def get_client(self):
        """Get or create Temporal client"""
        if self.client is None:
            self.client = await get_temporal_client()
        return self.client

    async def create_reminder_processing_schedule(self):
        """
        Create schedule for reminder processing (every minute)
        Replaces: 'task-reminders-check' cron job
        """
        try:
            client = await self.get_client()

            schedule_id = "reminder-processing-schedule"

            # Delete existing schedule if it exists
            try:
                handle = client.get_schedule_handle(schedule_id)
                await handle.delete()
                logger.info(f"Deleted existing schedule: {schedule_id}")
            except:
                pass  # Schedule doesn't exist, which is fine

            # Create new schedule
            from temporalio.client import Schedule

            handle = await client.create_schedule(
                schedule_id,
                Schedule(
                    spec=ScheduleSpec(
                        intervals=[
                            ScheduleIntervalSpec(
                                every=timedelta(minutes=1)
                            )  # Every minute
                        ]
                    ),
                    action=ScheduleActionStartWorkflow(
                        ReminderProcessingWorkflow.run,
                        id=f"reminder-processing-scheduled-{get_this_moment().strftime('%Y%m%d-%H%M%S')}",
                        task_queue=TASK_QUEUE_NAME,
                        execution_timeout=timedelta(minutes=30),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    ),
                ),
            )

            self.schedules[schedule_id] = handle
            logger.info(f"Created schedule: {schedule_id}")

            return {
                "status": "success",
                "schedule_id": schedule_id,
                "message": "Reminder processing schedule created",
            }

        except Exception as e:
            logger.error(f"Failed to create reminder processing schedule: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to create schedule: {str(e)}",
            }

    async def create_attendance_pdf_update_schedule(self):
        """
        Create schedule for attendance PDF update (every 6 hours)
        """
        try:
            client = await self.get_client()

            schedule_id = "attendance-pdf-update-schedule"

            # Delete existing schedule if it exists
            try:
                handle = client.get_schedule_handle(schedule_id)
                await handle.delete()
                logger.info(f"Deleted existing schedule: {schedule_id}")
            except:
                pass

            # Create new schedule
            from temporalio.client import Schedule

            handle = await client.create_schedule(
                schedule_id,
                Schedule(
                    spec=ScheduleSpec(
                        intervals=[
                            ScheduleIntervalSpec(
                                every=timedelta(hours=6)
                            )  # Every 6 hours
                        ]
                    ),
                    action=ScheduleActionStartWorkflow(
                        AttendancePDFUpdateWorkflow.run,
                        id=f"attendance-pdf-update-scheduled-{get_this_moment().strftime('%Y%m%d-%H%M%S')}",
                        task_queue=TASK_QUEUE_NAME,
                        execution_timeout=timedelta(hours=12),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    ),
                ),
            )

            self.schedules[schedule_id] = handle
            logger.info(f"Created schedule: {schedule_id}")

            return {
                "status": "success",
                "schedule_id": schedule_id,
                "message": "Attendance PDF update schedule created",
            }

        except Exception as e:
            logger.error(f"Failed to create attendance PDF update schedule: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to create schedule: {str(e)}",
            }

    async def setup_all_schedules(self):
        """
        Set up all schedules
        """
        logger.info("Setting up all Temporal schedules...")

        results = []

        # Create reminder processing schedule
        result = await self.create_reminder_processing_schedule()
        results.append(result)

        # Create attendance PDF update schedule (commented out due to table sizing issues)
        # Uncomment when the PDF generation issues are resolved
        # result = await self.create_attendance_pdf_update_schedule()
        # results.append(result)

        # Log results
        success_count = sum(1 for r in results if r["status"] == "success")
        total_count = len(results)

        logger.info(
            f"Schedule setup completed: {success_count}/{total_count} successful"
        )

        return {
            "status": "completed",
            "successful": success_count,
            "total": total_count,
            "results": results,
        }

    async def delete_schedule(self, schedule_id: str):
        """
        Delete a specific schedule
        """
        try:
            client = await self.get_client()

            handle = client.get_schedule_handle(schedule_id)
            await handle.delete()

            if schedule_id in self.schedules:
                del self.schedules[schedule_id]

            logger.info(f"Deleted schedule: {schedule_id}")

            return {
                "status": "success",
                "schedule_id": schedule_id,
                "message": "Schedule deleted successfully",
            }

        except Exception as e:
            logger.error(f"Failed to delete schedule {schedule_id}: {str(e)}")
            return {
                "status": "error",
                "schedule_id": schedule_id,
                "message": f"Failed to delete schedule: {str(e)}",
            }

    async def delete_all_schedules(self):
        """
        Delete all managed schedules
        """
        logger.info("Deleting all Temporal schedules...")

        schedule_ids = [
            "reminder-processing-schedule",
            "failed-reminder-retry-schedule",
            "attendance-pdf-update-schedule",  # Include this in case it exists
        ]

        results = []
        for schedule_id in schedule_ids:
            result = await self.delete_schedule(schedule_id)
            results.append(result)

        success_count = sum(1 for r in results if r["status"] == "success")
        total_count = len(results)

        logger.info(
            f"Schedule deletion completed: {success_count}/{total_count} successful"
        )

        return {
            "status": "completed",
            "successful": success_count,
            "total": total_count,
            "results": results,
        }

    async def list_schedules(self):
        """
        List all schedules
        """
        try:
            client = await self.get_client()

            # Note: This is a simplified version
            # In practice, you'd use Temporal's list schedules API

            return {
                "status": "success",
                "schedules": list(self.schedules.keys()),
                "message": "Use Temporal Web UI to see detailed schedule information",
            }

        except Exception as e:
            return {"status": "error", "message": f"Failed to list schedules: {str(e)}"}


# Global scheduler instance
temporal_scheduler = TemporalScheduler()


async def setup_all_schedules():
    """
    Standalone function to set up all schedules
    """
    return await temporal_scheduler.setup_all_schedules()


async def setup_schedules():
    """
    Convenience function to set up all schedules
    """
    return await temporal_scheduler.setup_all_schedules()


async def cleanup_schedules():
    """
    Convenience function to clean up all schedules
    """
    return await temporal_scheduler.delete_all_schedules()


if __name__ == "__main__":
    # Run schedule setup
    logging.basicConfig(level=logging.INFO)
    asyncio.run(setup_schedules())
