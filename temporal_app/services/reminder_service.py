"""
Temporal Service Layer for Reminder Management
This replaces the old Celery task triggering functions
"""

import os
import uuid
from datetime import timedelta
from typing import Any, Dict

from temporalio.common import RetryPolicy

from temporal_app.client import get_temporal_client
from temporal_app.workflows.reminder_workflows import (
    ComprehensiveReminderWorkflow, FailedReminderRetryWorkflow,
    PdfGenerationWorkflow, ReminderProcessingWorkflow)

task_queue_name = os.getenv("TEMPORAL_TASK_QUEUE_NAME")


class TemporalReminderService:
    """
    Service for triggering reminder workflows via Temporal
    """

    def __init__(self):
        self.client = None

    async def get_client(self):
        """Get or create Temporal client"""
        if self.client is None:
            self.client = await get_temporal_client()
        return self.client

    async def trigger_reminder_processing(self) -> Dict[str, Any]:
        """
        Trigger reminder processing workflow
        Replaces: send_task_reminders.delay()
        """
        try:
            client = await self.get_client()

            workflow_id = f"reminder-processing-{uuid.uuid4()}"

            handle = await client.start_workflow(
                ReminderProcessingWorkflow.run,
                id=workflow_id,
                task_queue=task_queue_name,
                execution_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return {
                "status": "started",
                "workflow_id": workflow_id,
                "run_id": handle.result_run_id,
                "message": "Reminder processing workflow started",
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start reminder processing: {str(e)}",
            }

    async def trigger_failed_reminder_retry(self) -> Dict[str, Any]:
        """
        Trigger failed reminder retry workflow
        Replaces: retry_failed_reminders.delay()
        """
        try:
            client = await self.get_client()

            workflow_id = f"failed-reminder-retry-{uuid.uuid4()}"

            handle = await client.start_workflow(
                FailedReminderRetryWorkflow.run,
                id=workflow_id,
                task_queue=task_queue_name,
                execution_timeout=timedelta(minutes=45),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )

            return {
                "status": "started",
                "workflow_id": workflow_id,
                "run_id": handle.result_run_id,
                "message": "Failed reminder retry workflow started",
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start failed reminder retry: {str(e)}",
            }

    async def trigger_reminder_summary_generation(
        self, project_code: str, force_regenerate: bool = False
    ) -> str:
        """
        Trigger reminder summary PDF generation workflow for a specific project
        Replaces: generate_reminder_summary_pdf_task.delay()

        Args:
            project_code: Project number to generate summary for
            force_regenerate: Whether to force regeneration even if PDF exists

        Returns:
            workflow_id: The ID of the started workflow
        """
        try:
            client = await self.get_client()

            workflow_id = f"reminder-summary-{project_code}-{uuid.uuid4()}"

            from temporal_app.workflows.reminder_workflows import \
                ProjectReminderSummaryWorkflow

            handle = await client.start_workflow(
                ProjectReminderSummaryWorkflow.run,
                args=[project_code, force_regenerate],
                id=workflow_id,
                task_queue=task_queue_name,
                execution_timeout=timedelta(hours=1),  # PDF generation can take time
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return workflow_id

        except Exception as e:
            raise Exception(
                f"Failed to start reminder summary generation workflow: {str(e)}"
            )

    async def trigger_pdf_generation(
        self,
        client_id: str,
        start_date: str,
        end_date: str,
        include_completed: bool = False,
    ) -> Dict[str, Any]:
        """
        Trigger PDF generation workflow
        Replaces: generate_reminder_summary_pdf.delay()
        """
        try:
            client = await self.get_client()

            workflow_id = f"pdf-generation-{client_id}-{uuid.uuid4()}"

            handle = await client.start_workflow(
                PdfGenerationWorkflow.run,
                args=[client_id, start_date, end_date, include_completed],
                id=workflow_id,
                task_queue=task_queue_name,
                execution_timeout=timedelta(hours=1),  # PDF generation can take time
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return {
                "status": "started",
                "workflow_id": workflow_id,
                "run_id": handle.result_run_id,
                "client_id": client_id,
                "message": f"PDF generation workflow started for client {client_id}",
            }

        except Exception as e:
            return {
                "status": "error",
                "client_id": client_id,
                "message": f"Failed to start PDF generation: {str(e)}",
            }

    async def trigger_comprehensive_workflow(
        self, operation: str, **kwargs
    ) -> Dict[str, Any]:
        """
        Trigger comprehensive workflow for any operation
        """
        try:
            client = await self.get_client()

            workflow_id = f"comprehensive-{operation}-{uuid.uuid4()}"

            handle = await client.start_workflow(
                ComprehensiveReminderWorkflow.run,
                args=[operation],
                kwargs=kwargs,
                id=workflow_id,
                task_queue=task_queue_name,
                execution_timeout=timedelta(hours=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            return {
                "status": "started",
                "workflow_id": workflow_id,
                "run_id": handle.result_run_id,
                "operation": operation,
                "parameters": kwargs,
                "message": f"Comprehensive workflow started for operation: {operation}",
            }

        except Exception as e:
            return {
                "status": "error",
                "operation": operation,
                "message": f"Failed to start comprehensive workflow: {str(e)}",
            }

    async def get_workflow_result(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get workflow result by ID
        Replaces: AsyncResult(task_id).get()
        """
        try:
            client = await self.get_client()

            handle = client.get_workflow_handle(workflow_id)

            # Check if workflow is running
            describe = await handle.describe()

            if describe.status.name == "RUNNING":
                return {
                    "status": "running",
                    "workflow_id": workflow_id,
                    "message": "Workflow is still running",
                }
            elif describe.status.name == "COMPLETED":
                result = await handle.result()
                return {
                    "status": "completed",
                    "workflow_id": workflow_id,
                    "result": result,
                }
            elif describe.status.name == "FAILED":
                return {
                    "status": "failed",
                    "workflow_id": workflow_id,
                    "error": str(describe.close_time),
                }
            else:
                return {
                    "status": describe.status.name.lower(),
                    "workflow_id": workflow_id,
                    "message": f"Workflow status: {describe.status.name}",
                }

        except Exception as e:
            return {
                "status": "error",
                "workflow_id": workflow_id,
                "message": f"Failed to get workflow result: {str(e)}",
            }

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Cancel a running workflow
        """
        try:
            client = await self.get_client()

            handle = client.get_workflow_handle(workflow_id)
            await handle.cancel()

            return {
                "status": "cancelled",
                "workflow_id": workflow_id,
                "message": "Workflow cancelled successfully",
            }

        except Exception as e:
            return {
                "status": "error",
                "workflow_id": workflow_id,
                "message": f"Failed to cancel workflow: {str(e)}",
            }

    async def list_running_workflows(self) -> Dict[str, Any]:
        """
        List all running workflows
        """
        try:
            client = await self.get_client()

            # This is a simplified version - in production you might want
            # to use Temporal's visibility API to list workflows
            return {
                "status": "success",
                "message": "Use Temporal Web UI or CLI to list workflows",
            }

        except Exception as e:
            return {"status": "error", "message": f"Failed to list workflows: {str(e)}"}


# Global service instance
temporal_reminder_service = TemporalReminderService()
