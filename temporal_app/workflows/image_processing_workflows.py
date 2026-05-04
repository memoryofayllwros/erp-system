"""
Image Processing Workflows for Temporal
These workflows handle the collection and processing of worker card images.
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import directly instead of using imports_passed_through
from temporal_app.activities.image_processing_activities import (
    check_image_collection_activity, process_collected_images_activity)


@workflow.defn
class ImageCollectionWorkflow:
    """
    Workflow for collecting and processing worker card images
    """

    @workflow.run
    async def run(self, sender: str, timeout_seconds: float = 30) -> Dict[str, Any]:
        """
        Main workflow for image collection and processing

        Args:
            sender: The WhatsApp sender ID
            timeout_seconds: Timeout in seconds before collection is processed

        Returns:
            Dictionary with processing results
        """
        try:
            workflow.logger.info(
                f"Starting image collection workflow for {sender} with {timeout_seconds} second timeout"
            )

            # Wait for the timeout period
            await workflow.sleep(timeout_seconds)

            # Check if collection is ready for processing
            check_result = await workflow.execute_activity(
                check_image_collection_activity,
                args=[sender, timeout_seconds],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                ),
            )

            if not check_result.get("ready", False):
                workflow.logger.info(
                    f"Collection not ready for {sender}, status: {check_result.get('status')}"
                )
                return check_result

            # Process the collected images
            process_result = await workflow.execute_activity(
                process_collected_images_activity,
                args=[sender],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                ),
            )

            workflow.logger.info(
                f"Image processing completed for {sender}: {process_result}"
            )
            return process_result

        except Exception as e:
            workflow.logger.error(
                f"Error in image collection workflow for {sender}: {str(e)}"
            )
            return {"status": "error", "sender": sender, "error": str(e)}


@workflow.defn
class ImageProcessingWorkflow:
    """
    Workflow for immediate processing of worker card images
    """

    @workflow.run
    async def run(self, sender: str) -> Dict[str, Any]:
        """
        Process images immediately without waiting

        Args:
            sender: The WhatsApp sender ID

        Returns:
            Dictionary with processing results
        """
        try:
            workflow.logger.info(
                f"Starting immediate image processing workflow for {sender}"
            )

            # Process the collected images
            process_result = await workflow.execute_activity(
                process_collected_images_activity,
                args=[sender],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                ),
            )

            workflow.logger.info(
                f"Immediate image processing completed for {sender}: {process_result}"
            )
            return process_result

        except Exception as e:
            workflow.logger.error(
                f"Error in immediate image processing workflow for {sender}: {str(e)}"
            )
            return {"status": "error", "sender": sender, "error": str(e)}
