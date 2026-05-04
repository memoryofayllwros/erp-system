"""
Temporal Workflows for Reminder Management
Workflows orchestrate activities and handle business logic
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities directly instead of using imports_passed_through
from temporal_app.activities.reminder_activities import (
    generate_reminder_summary_pdf, get_reminder_summary_info,
    process_task_reminders, retry_failed_reminders)


@workflow.defn
class ReminderProcessingWorkflow:
    """
    Workflow for processing task reminders
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """
        Main workflow execution
        """
        try:
            # Configure retry policy
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(minutes=5),
                maximum_attempts=3,
                backoff_coefficient=2.0,
            )

            # Execute the reminder processing activity
            result = await workflow.execute_activity(
                process_task_reminders,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Reminder processing completed: {result}")
            return result

        except Exception as e:
            workflow.logger.error(f"Error in ReminderProcessingWorkflow: {str(e)}")
            raise


@workflow.defn
class FailedReminderRetryWorkflow:
    """
    Workflow for retrying failed reminders
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """
        Retry failed reminders workflow
        """
        try:
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=5),
                maximum_attempts=5,
                backoff_coefficient=2.0,
            )

            result = await workflow.execute_activity(
                retry_failed_reminders,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Failed reminder retry completed: {result}")
            return result

        except Exception as e:
            workflow.logger.error(f"Error in FailedReminderRetryWorkflow: {str(e)}")
            raise


@workflow.defn
class ProjectReminderSummaryWorkflow:
    """
    Workflow for generating project-specific reminder summary PDFs
    """

    @workflow.run
    async def run(
        self, project_code: str, force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Generate reminder summary PDF for a specific project
        """
        try:
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            )

            # Generate the reminder summary PDF
            from temporal_app.activities.reminder_activities import \
                generate_project_reminder_summary_pdf

            result = await workflow.execute_activity(
                generate_project_reminder_summary_pdf,
                args=[project_code, force_regenerate],
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=retry_policy,
            )

            return {"status": "success", "project_code": project_code, "result": result}

        except Exception as e:
            workflow.logger.error(
                f"PDF generation failed for project {project_code}: {str(e)}"
            )
            return {"status": "error", "project_code": project_code, "error": str(e)}


@workflow.defn
class PdfGenerationWorkflow:
    """
    Workflow for generating reminder summary PDFs
    """

    @workflow.run
    async def run(
        self,
        client_id: str,
        start_date: str,
        end_date: str,
        include_completed: bool = False,
    ) -> Dict[str, Any]:
        """
        PDF generation workflow
        """
        try:
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=15),
                maximum_interval=timedelta(minutes=10),
                maximum_attempts=3,
                backoff_coefficient=2.0,
            )

            # First get summary info
            summary_info = await workflow.execute_activity(
                get_reminder_summary_info,
                args=[client_id, start_date, end_date, include_completed],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            # Then generate PDF if summary info is successful
            if summary_info.get("status") == "success":
                pdf_result = await workflow.execute_activity(
                    generate_reminder_summary_pdf,
                    args=[client_id, start_date, end_date, include_completed],
                    start_to_close_timeout=timedelta(
                        minutes=20
                    ),  # PDF generation can take longer
                    retry_policy=retry_policy,
                )

                # Combine results
                return {
                    "status": "success",
                    "summary_info": summary_info,
                    "pdf_result": pdf_result,
                    "client_id": client_id,
                }
            else:
                workflow.logger.warning(f"Summary info failed for client {client_id}")
                return {
                    "status": "failed",
                    "error": "Failed to get summary info",
                    "summary_info": summary_info,
                    "client_id": client_id,
                }

        except Exception as e:
            workflow.logger.error(f"Error in PdfGenerationWorkflow: {str(e)}")
            raise


@workflow.defn
class ScheduledReminderWorkflow:
    """
    Long-running workflow for scheduled reminder processing
    This replaces Celery Beat functionality
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """
        Scheduled reminder processing with built-in retry and error handling
        """
        processed_count = 0

        while True:
            try:
                # Process reminders
                result = await workflow.execute_activity(
                    process_task_reminders,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(minutes=2),
                        maximum_attempts=3,
                    ),
                )

                processed_count += result.get("processed", 0)
                workflow.logger.info(
                    f"Processed {result.get('processed', 0)} reminders. Total: {processed_count}"
                )

                # Wait 1 minute before next execution (replaces cron schedule)
                await workflow.sleep(60)

            except Exception as e:
                workflow.logger.error(
                    f"Error in scheduled reminder processing: {str(e)}"
                )

                # Wait longer on error before retrying
                await workflow.sleep(300)  # 5 minutes


@workflow.defn
class ComprehensiveReminderWorkflow:
    """
    Comprehensive workflow that handles all reminder operations
    """

    @workflow.run
    async def run(self, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Multi-purpose workflow based on operation type
        """
        try:
            if operation == "process_reminders":
                return await workflow.execute_activity(
                    process_task_reminders,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

            elif operation == "retry_failed":
                return await workflow.execute_activity(
                    retry_failed_reminders,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )

            elif operation == "generate_pdf":
                client_id = kwargs.get("client_id", "")
                start_date = kwargs.get("start_date", "")
                end_date = kwargs.get("end_date", "")
                include_completed = kwargs.get("include_completed", False)

                if not client_id or not start_date or not end_date:
                    return {
                        "status": "error",
                        "message": "Missing required parameters for PDF generation",
                    }

                # First get summary info
                summary_info = await workflow.execute_activity(
                    get_reminder_summary_info,
                    args=[client_id, start_date, end_date, include_completed],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                # Then generate PDF
                pdf_result = await workflow.execute_activity(
                    generate_reminder_summary_pdf,
                    args=[client_id, start_date, end_date, include_completed],
                    start_to_close_timeout=timedelta(minutes=20),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                return {
                    "status": "success",
                    "summary_info": summary_info,
                    "pdf_result": pdf_result,
                }

            else:
                return {"status": "error", "message": f"Unknown operation: {operation}"}

        except Exception as e:
            workflow.logger.error(f"Error in ComprehensiveReminderWorkflow: {str(e)}")
            return {"status": "error", "operation": operation, "error": str(e)}
