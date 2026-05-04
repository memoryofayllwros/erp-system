"""
Image Processing Activities for Temporal Workflows
These activities handle the processing of worker card images after collection.
"""

import logging
from typing import Any, Dict

from temporalio import activity

from datetime import datetime
from src.utils.datetime_standarization_helpers import HK_TZ, get_this_moment

# Import necessary modules
from infrastructure.redis_connection.redis_manager import (clear_image_collection,
                                            get_image_collection)

logger = logging.getLogger(__name__)


@activity.defn
async def process_collected_images_activity(sender: str) -> Dict[str, Any]:
    """
    Process collected worker card images for a sender

    Args:
        sender: The WhatsApp sender ID

    Returns:
        Dictionary with processing results
    """
    logger.info(f"Starting image processing activity for {sender}")

    # Move imports here to avoid sandboxing issues
    from src.message_templates.message_response_templates import send_whatsapp_message_back
    from src.chatbot_service.langgraph.agent import compiled_graph
    from src.chatbot_service.langgraph.state import WorkflowState
    from infrastructure.redis_connection.redis_manager import (load_previous_state,
                                                redis_manager)

    try:
        # Get the image collection from Redis
        collection = await get_image_collection(sender)

        if not collection:
            logger.info(f"No image collection found for {sender}")
            return {"status": "no_collection", "sender": sender, "processed": 0}

        # Extract image URLs from collection
        image_urls = collection.get("images", [])
        image_count = len(image_urls)

        if image_count == 0:
            logger.info(f"No images found in collection for {sender}")
            return {"status": "no_images", "sender": sender, "processed": 0}

        # Get original body from collection - this contains the project info
        original_body = collection.get("original_body", "")

        logger.info(
            f"Processing {image_count} images for {sender}, original_body: {original_body}"
        )

        # Load previous state from Redis to understand the conversation context
        previous_state = await load_previous_state(sender)

        # Create the state for processing with proper workflow entry point
        if previous_state and previous_state.get("current_intent"):
            # If we already classified intent, continue from entity extraction
            logger.info(
                f"Previous intent found: {previous_state.get('current_intent')}, continuing from entity extraction"
            )

            current_state = WorkflowState(
                messages=previous_state.get("messages", []),
                current_intent=previous_state.get(
                    "current_intent"
                ),  # Keep existing intent
                extracted_fields=previous_state.get("extracted_fields", {}),
                validated=False,
                status="intent_detected",  # Start from entity extraction since intent is known
                action_result="",
                error=False,
                media_urls=image_urls,
                image_collection_active=False,  # Collection is done
                image_collection_processed=True,  # Mark as processed
                image_count=image_count,
                collected_image_count=image_count,
                original_body=original_body,
            )

            # Ensure the last message body uses original body for context
            if current_state["messages"] and original_body:
                current_state["messages"][-1]["content"]["Body"] = original_body
                logger.info(f"Updated last message with original body: {original_body}")

        else:
            # No previous intent, start from intent classification with original body
            logger.info(
                f"No previous intent found, starting from intent classification with original body"
            )

            # Create message with original body for intent classification
            message_body = original_body if original_body else "add workers"

            current_state = WorkflowState(
                messages=[
                    {
                        "role": "user",
                        "content": {
                            "Body": message_body,
                            "From": sender,
                            "MediaUrl0": (
                                image_urls[0] if image_urls else None
                            ),  # Include first image for compatibility
                        },
                    }
                ],
                current_intent="",  # Will be classified
                extracted_fields={},
                validated=False,
                status="await_intent",  # Start from intent classification
                action_result="",
                error=False,
                media_urls=image_urls,
                image_collection_active=False,  # Collection is done
                image_collection_processed=True,  # Mark as processed
                image_count=image_count,
                collected_image_count=image_count,
                original_body=original_body,
            )

        final_state = await compiled_graph.ainvoke(current_state)

        logger.info(f"Workflow completed with status: {final_state.get('status')}")

        response_message = final_state.get("action_result", "")

        fallback_message = (
            response_message or "✅ Worker registration completed successfully."
        )
        await send_whatsapp_message_back(fallback_message, sender)
        logger.info(f"Sent fallback message to {sender}: {fallback_message}")

        await clear_image_collection(sender)
        logger.info(f"Cleared image collection for {sender}")

        if not final_state.get("error", False):
            await redis_manager.clear_state(sender)
            logger.info(f"Cleared conversation state for {sender}")

        logger.info(f"Successfully processed {image_count} images for {sender}")

        return {
            "status": "success",
            "sender": sender,
            "processed": image_count,
            "original_body": original_body,
            "final_status": final_state.get("status"),
        }

    except Exception as e:
        logger.error(f"Error processing images for {sender}: {str(e)}", exc_info=True)

        # Send error message to user only once
        try:
            error_msg = "⚠️ There was an issue processing your worker cards. Please try sending your request again."
            await send_whatsapp_message_back(error_msg, sender)
            logger.info(f"Sent error message to {sender}")
        except Exception as inner_e:
            logger.error(f"Error sending error message: {str(inner_e)}")

        return {
            "status": "error",
            "sender": sender,
            "error": str(e),
            "processed": 0,
        }


@activity.defn
async def check_image_collection_activity(
    sender: str, timeout_seconds: float = 30
) -> Dict[str, Any]:
    """
    Check if an image collection is ready for processing

    Args:
        sender: The WhatsApp sender ID
        timeout_seconds: Timeout in seconds before collection is considered ready

    Returns:
        Dictionary with collection status
    """
    try:
        logger.info(f"Checking image collection for {sender}")

        # Get the image collection
        collection = await get_image_collection(sender)

        if not collection:
            logger.info(f"No collection found for {sender}")
            return {"status": "no_collection", "sender": sender, "ready": False}

        # Get the last_updated timestamp from the collection
        last_updated_str = collection.get("last_updated")
        if not last_updated_str:
            logger.info(f"No last_updated timestamp in collection for {sender}")
            return {
                "status": "no_timestamp",
                "sender": sender,
                "ready": True,  # Assume ready if no timestamp
            }

        # Parse the timestamp
        try:

            last_updated = datetime.fromisoformat(last_updated_str)

            # Ensure timezone awareness
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(HK_TZ)
            current_time = get_this_moment()
            time_since_update = (current_time - last_updated).total_seconds()

        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing timestamp for {sender}: {e}")
            return {
                "status": "invalid_timestamp",
                "sender": sender,
                "ready": True,  # Assume ready if timestamp is invalid
            }

        # Check if enough time has passed
        is_ready = time_since_update >= timeout_seconds

        image_count = len(collection.get("images", []))

        logger.info(
            f"Collection readiness check for {sender}: "
            f"{image_count} images, "
            f"last updated {time_since_update:.1f}s ago, "
            f"timeout: {timeout_seconds}s, "
            f"ready: {is_ready}"
        )

        return {
            "status": "success",
            "sender": sender,
            "ready": is_ready,
            "image_count": image_count,
            "time_since_update": time_since_update,
            "timeout_seconds": timeout_seconds,
        }

    except Exception as e:
        logger.error(f"Error checking collection for {sender}: {str(e)}")
        return {"status": "error", "sender": sender, "error": str(e), "ready": False}
