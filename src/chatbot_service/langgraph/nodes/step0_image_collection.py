"""
Enhanced Multi-Image Collection Handler
This step manages collecting multiple images from WhatsApp for worker registration with improved reliability and user experience.
"""

import asyncio
import logging
from typing import Any, Dict

from temporal_app.client import get_temporal_client
from temporal_app.worker import TASK_QUEUE_NAME
from infrastructure.redis_connection.redis_manager import (ImageCollectionError,
                                            _continue_with_normal_flow)

logger = logging.getLogger(__name__)


async def schedule_temporal_workflow(sender: str, timeout_seconds: float = 30) -> bool:
    """Schedule image processing using Temporal workflow"""
    try:
        client = await get_temporal_client()

        from temporal_app.workflows.image_processing_workflows import \
            ImageCollectionWorkflow

        handle = await client.start_workflow(
            ImageCollectionWorkflow.run,
            args=[sender, timeout_seconds],
            id=f"image-collection-{sender}-{asyncio.get_event_loop().time()}",
            task_queue=TASK_QUEUE_NAME,
        )

        logger.info(
            f"Scheduled temporal workflow: {handle.id} for {sender} with {timeout_seconds}s timeout"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to schedule Temporal workflow: {str(e)}")
        return False


async def image_collection_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced image collector that handles both image collection and done commands.
    This is where state modifications actually persist (unlike condition functions).
    """
    logger = logging.getLogger(__name__)
    logger.info(
        f"Step 0: Enhanced image collector processing state: {state.get('status', 'unknown')}"
    )

    try:
        user_messages = [m for m in reversed(state["messages"]) if m["role"] == "user"]
        if not user_messages:
            logger.warning("No user messages found in state")
            return _continue_with_normal_flow(state)

        current_message = user_messages[0]["content"]
        sender = current_message.get("From", "")
        body = current_message.get("Body", "").lower().strip()

        is_done_command = body in ["done", "end", "完成"]

        if is_done_command:
            logger.info("User indicated collection completion with 'done' command")

            state["done_command_received"] = True
            logger.info(
                f"✅ DONE COMMAND RECEIVED - Flag set to: {state['done_command_received']}"
            )

            # Use the current state data instead of trying to get it from Redis
            # The state already contains all the image information we need
            current_image_count = len(state.get("media_urls", []))
            current_original_body = state.get("original_body", "")

            if current_image_count > 0:
                logger.info(
                    f"✅ DONE command processed using state data: images={current_image_count}, original_body='{current_original_body}'"
                )

                # Keep the current state data, just mark collection as complete
                state["image_collection_active"] = False
                state["image_collection_processed"] = True
                state["status"] = "await_intent"

                # Ensure we have the extracted fields for the cards
                if "extracted_fields" not in state:
                    state["extracted_fields"] = {}

                # Add the card images to extracted fields for processing
                state["extracted_fields"]["card_images"] = state.get("media_urls", [])
                logger.info(
                    f"Added {len(state.get('media_urls', []))} card images to extracted_fields for processing"
                )

            else:
                logger.warning("No images found in state for done command")
                state["image_count"] = 0
                state["collected_image_count"] = 0
                state["media_urls"] = []
                state["image_collection_active"] = False
                state["image_collection_processed"] = True
                state["status"] = "await_intent"

            return state

        # Handle regular image collection (non-done commands)
        media_url = current_message.get("MediaUrl0")
        state_media_urls = state.get("media_urls", [])

        # Use the deduplication function from redis_manager for consistent URL handling
        from infrastructure.redis_connection.redis_manager import redis_manager

        # Improved deduplication of existing state media URLs
        if state_media_urls:
            state["media_urls"] = redis_manager.deduplicate_media_urls(state_media_urls)
            if len(state_media_urls) != len(state["media_urls"]):
                logger.info(
                    f"Deduplicated state media_urls: {len(state_media_urls)} -> {len(state['media_urls'])}"
                )

        has_media = bool(media_url) or bool(state["media_urls"])

        if not has_media:
            logger.info("No media detected in message, continuing with normal flow")
            return _continue_with_normal_flow(state)

        # Handle media collection
        logger.info(f"Processing media collection for {sender}")

        original_body = state.get("original_body", "")

        try:
            # For regular image collection, use the state data as the source of truth
            # Only add new images to Redis if we have a new media_url
            if media_url:
                from infrastructure.redis_connection.redis_manager import redis_manager

                image_count = await redis_manager.add_image_to_collection(
                    sender, media_url, original_body=original_body or body
                )
                logger.info(
                    f"Added image to collection for {sender}: {media_url}, total: {image_count}"
                )

                # Update state with new image - only if not already present
                current_images = state.get("media_urls", [])
                if media_url not in current_images:
                    current_images.append(media_url)
                    state["media_urls"] = current_images
                    state["image_count"] = len(current_images)
                    state["collected_image_count"] = len(current_images)
                    logger.info(f"Added new image to state: {media_url}")
                else:
                    logger.info(f"Image already present in state: {media_url}")

            # Use the current state data instead of trying to sync with Redis
            # The state already contains all the image information we need
            current_images = state.get("media_urls", [])
            if current_images:
                # Ensure the state reflects the current image count
                state["image_count"] = len(current_images)
                state["collected_image_count"] = len(current_images)
                logger.info(f"Using {len(current_images)} images from current state")

                # Schedule temporal workflow on first image if this is a new collection
                if len(current_images) == 1:
                    logger.info(
                        "First image in collection, scheduling temporal workflow"
                    )
                    timeout_seconds = 30  # 30 second timeout
                    temporal_scheduled = await schedule_temporal_workflow(
                        sender, timeout_seconds
                    )
                    if temporal_scheduled:
                        logger.info(
                            f"Temporal workflow scheduled successfully for {sender}"
                        )
                    else:
                        logger.warning(
                            f"Failed to schedule temporal workflow for {sender}"
                        )

                # Set collection state
                state["image_collection_active"] = True
                state["image_collection_processed"] = False
                state["status"] = "collecting_images"
                # Ensure done_command_received is properly initialized for regular collection
                if "done_command_received" not in state:
                    state["done_command_received"] = False

                logger.info(
                    f"Collection updated for {sender}: {len(current_images)} images total"
                )
                return state

        except ImageCollectionError as e:
            logger.error(f"Collection error for {sender}: {str(e)}")
            error_message = str(e)
            state["error"] = True
            state["action_result"] = error_message
            return state

        except Exception as e:
            logger.error(
                f"Unexpected error in image collection for {sender}: {str(e)}",
                exc_info=True,
            )
            error_message = f"⚠️ Error processing images: {str(e)}"
            state["error"] = True
            state["action_result"] = error_message
            return state

        # Fallback: continue with normal flow if nothing else applies
        logger.info("Continuing with normal flow after image processing attempt")
        return state

    except Exception as e:
        logger.error(
            f"Critical error in image_collection_node for {sender}: {str(e)}",
            exc_info=True,
        )
        error_message = f"⚠️ Critical error in image processing: {str(e)}"
        state["error"] = True
        state["action_result"] = error_message
        return state
