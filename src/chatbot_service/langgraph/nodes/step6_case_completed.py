import asyncio
import logging
import os
from typing import Any, Dict, Optional

from src.message_templates.message_response_templates import send_whatsapp_message_back
from src.chatbot_service.llm_prompts.classification_prompts.fallback_prompts import \
    falldown_smalltalk_response
from infrastructure.redis_connection.redis_manager import (clear_image_collection,
                                            clear_state, redis_manager)

redis_key_prefix = os.getenv("REDIS_KEY_PREFIX")

logger = logging.getLogger(__name__)


async def case_completed_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate appropriate responses based on the current state of the conversation.

    This node:
    1. Analyzes the current workflow state
    2. Determines the appropriate response type
    3. Sends the response to the user
    4. Updates state and handles cleanup as needed
    """

    logger.info(
        f"Step 6 case_completed: Processing state with status='{state.get('status')}', "
        f"error={state.get('error')}, "
        f"image_collection_active={state.get('image_collection_active')}"
    )

    try:
        # Extract sender information
        sender = _extract_sender(state)
        if not sender:
            logger.error("Cannot proceed without sender information")
            return state

        # Check Redis health before proceeding
        redis_healthy = await _check_redis_health()
        if not redis_healthy:
            logger.warning("Redis health check failed, proceeding without cleanup")
            # Still process the response but mark Redis as unhealthy
            state["redis_unhealthy"] = True

        # Determine response type based on current state
        response_type = _determine_response_type(state)
        logger.info(f"Determined response type: {response_type}")

        # Route to appropriate handler
        if response_type == "success":
            return await _handle_success_response(state, sender)
        elif response_type == "error":
            return await _handle_error_response(state, sender)
        elif response_type == "image_collection":
            return await _handle_image_collection_response(state, sender)
        elif response_type == "await_field":
            return await _handle_await_field_response(state, sender)
        else:
            logger.warning(
                f"Unknown response type: {response_type}, defaulting to error"
            )
            return await _handle_error_response(state, sender)

    except Exception as e:
        logger.error(f"Critical error in case_completed: {str(e)}", exc_info=True)
        return await _handle_critical_error(state, e)


async def _check_redis_health() -> bool:
    """
    Quick health check for Redis connectivity.
    Returns True if Redis is accessible, False otherwise.
    """
    try:
        async with redis_manager.get_client() as client:
            # Simple ping with timeout
            await asyncio.wait_for(client.ping(), timeout=2.0)
            return True
    except asyncio.TimeoutError:
        logger.warning("Redis ping timed out")
        return False
    except Exception as e:
        logger.warning(f"Redis health check failed: {str(e)}")
        return False


def _extract_sender(state: Dict[str, Any]) -> str:
    """Extract sender from state messages"""
    try:
        user_messages = [
            m for m in state.get("messages", []) if m.get("role") == "user"
        ]
        if not user_messages:
            logger.warning("No user messages found in state")
            return ""

        sender = user_messages[-1].get("content", {}).get("From", "")
        if not sender:
            logger.warning("No sender information found in latest message")

        return sender
    except Exception as e:
        logger.error(f"Error extracting sender: {str(e)}")
        return ""


def _determine_response_type(state: Dict[str, Any]) -> str:
    """
    Determine the appropriate response type based on current state.

    Priority order:
    1. Location data handling (special case)
    2. Error conditions
    3. Successful completion (CRUD executed or done command processed)
    4. Image collection in progress
    5. Awaiting more information
    """

    # First check for location data (highest priority)
    has_location_data = False
    if state.get("messages") and len(state.get("messages", [])) > 0:
        latest_message = state["messages"][-1].get("content", {})
        has_location_data = latest_message.get("Latitude") and latest_message.get(
            "Longitude"
        )

    # If we have location data, override error flag and set action_result if needed
    if has_location_data:
        # Check if we already have a meaningful action_result
        if not state.get("action_result"):
            state["action_result"] = (
                "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
            )

        # Set intent if not already set
        if not state.get("current_intent") or state.get("current_intent") not in {
            "add_project_gps"
        }:
            state["current_intent"] = "add_project_gps"

        # Clear error flag if it was set
        if state.get("error", False):
            state["error"] = False

        # Set appropriate status
        if state.get("status") not in {"slot_filled", "success", "CRUD_EXECUTED"}:
            state["status"] = "await_field"

        logger.info(
            "Response type: SUCCESS - Location data detected, overriding other conditions"
        )
        return "success"

    # Check for error conditions
    if state.get("error", False):
        logger.info("Response type: ERROR - Error flag is set")
        return "error"

    # Extract status and action_result for easier access
    status = state.get("status", "")
    has_action_result = bool(state.get("action_result"))

    # Check for active image collection
    image_collection_processed = state.get("image_collection_processed", False)
    image_count = state.get("image_count", 0)

    if state.get("status") == "collecting_images":
        logger.info(
            f"Response type: IMAGE_COLLECTION - processed={image_collection_processed}, count={image_count}"
        )
        return "image_collection"

    # Check for successful completion
    if status in ["success", "CRUD_EXECUTED"] or (
        status == "slot_filled" and has_action_result
    ):
        logger.info(
            f"Response type: SUCCESS - status={status}, has_result={has_action_result}"
        )
        return "success"

    # Check if we have an action result for await_field status
    if status == "await_field" and has_action_result:
        logger.info(f"Response type: AWAIT_FIELD - has action result")
        return "await_field"

    # Check if we have any action result but it's not covered by the above cases
    if has_action_result:
        logger.info(
            f"Response type: SUCCESS - has action result but not in success status"
        )
        return "success"

    # Default fallback
    logger.warning(
        f"Response type: UNKNOWN - defaulting to await_field. Status: {status}"
    )
    return "await_field"


async def _handle_success_response(
    state: Dict[str, Any], sender: str
) -> Dict[str, Any]:
    """Handle successful completion response with comprehensive cleanup handling"""
    try:
        result_message = state.get(
            "action_result", "✅ Operation completed successfully."
        )

        # Handle both string and dict responses
        if isinstance(result_message, dict):
            # Extract message from dict response
            result_message = result_message.get("message", "✅ Your request has been processed successfully.")
        elif not result_message or (isinstance(result_message, str) and result_message.strip() == ""):
            result_message = "✅ Your request has been processed successfully."

        # Send success message first (most important part)
        await send_whatsapp_message_back(result_message, sender)
        logger.info(f"Success response sent to {sender}: {result_message[:100]}...")

        # Update state to mark message as sent BEFORE cleanup
        state["status"] = "success"

        # Clear accumulated data from successful intent processing
        logger.info(
            f"Clearing accumulated data for successful intent: {state.get('current_intent', 'unknown')}"
        )

        # Clear media URLs that were accumulated during processing
        if "media_urls" in state:
            original_count = len(state["media_urls"])
            state["media_urls"] = []
            logger.info(f"Cleared {original_count} accumulated media URLs for {sender}")

        # Clear extracted fields that were processed
        if "extracted_fields" in state:
            original_fields = len(state["extracted_fields"])
            state["extracted_fields"] = {}
            logger.info(f"Cleared {original_fields} extracted fields for {sender}")

        # Clear image collection related fields
        state["image_collection_active"] = False
        state["image_collection_processed"] = False
        state["image_count"] = 0
        state["collected_image_count"] = 0
        state["collection_timeout_passed"] = False

        # Clear validation flags
        state["validated"] = False

        # Clear any temporary processing flags
        if "done_command_received" in state:
            state["done_command_received"] = False

        # Attempt comprehensive cleanup only if Redis is healthy
        redis_healthy = not state.get("redis_unhealthy", False)
        if redis_healthy:
            logger.info(f"Starting comprehensive cleanup for {sender}")

            # Step 1: Safe cleanup conversation state (includes both state and image collection)
            cleanup_success = await _safe_cleanup_conversation_state(sender)
            if cleanup_success:
                logger.info(f"Safe cleanup completed successfully for {sender}")
            else:
                logger.warning(
                    f"Safe cleanup failed for {sender}, attempting direct Redis cleanup"
                )

                # Step 2: Direct Redis cleanup as fallback
                try:
                    # Clear conversation state directly
                    await clear_state(sender)
                    logger.debug(f"Direct state clearing completed for {sender}")

                    # Clear image collection directly
                    await clear_image_collection(sender)
                    logger.debug(
                        f"Direct image collection clearing completed for {sender}"
                    )

                    # Clear any additional Redis keys for this sender
                    async with redis_manager.get_client() as client:
                        pattern = f"{redis_key_prefix}:*:{sender}"
                        keys = await client.keys(pattern)

                        if keys:
                            deleted_count = await client.delete(*keys)
                            logger.debug(
                                f"Direct Redis cleanup: cleared {deleted_count} additional keys for {sender}"
                            )
                        else:
                            logger.debug(f"No additional Redis keys found for {sender}")

                    logger.info(
                        f"Direct Redis cleanup completed successfully for {sender}"
                    )

                except Exception as direct_cleanup_error:
                    logger.error(
                        f"Direct Redis cleanup also failed for {sender}: {str(direct_cleanup_error)}"
                    )
                    # Don't change success status - the user operation was successful
        else:
            logger.info(f"Skipping cleanup for {sender} due to Redis health issues")

        return state

    except Exception as e:
        logger.error(f"Error in success response handler: {str(e)}", exc_info=True)
        # Fallback to basic success message if main message failed
        await send_whatsapp_message_back("✅ Operation completed.", sender)
        state["error"] = True  # Mark as error if we can't even send a message
        return state


async def _handle_error_response(state: Dict[str, Any], sender: str) -> Dict[str, Any]:
    """Handle error response with user-friendly messaging"""
    try:
        # Check for location data first (highest priority)
        has_location_data = False
        if state.get("messages") and len(state.get("messages", [])) > 0:
            latest_message = state["messages"][-1].get("content", {})
            has_location_data = latest_message.get("Latitude") and latest_message.get(
                "Longitude"
            )

        # If we have location data, provide a specific helpful message
        if has_location_data:
            error_message = "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
            # Set intent to add_project_gps
            state["current_intent"] = "add_project_gps"
            # Clear error flag
            state["error"] = False
            # Set appropriate status
            state["status"] = "await_field"
        else:
            # Regular error handling
            error_message = state.get("action_result", "")

            # Handle both string and dict responses
            if isinstance(error_message, dict):
                # Extract message from dict response
                error_message = error_message.get("message", "")
            
            # Provide user-friendly error message based on error cause
            if not error_message or (isinstance(error_message, str) and error_message.strip() == ""):
                # If action_result is empty, look for the actual error cause
                logger.warning(f"No action_result found in state. Checking for error causes.")
                logger.info(f"Current intent: {state.get('current_intent')}, Status: {state.get('status')}")
                
                # Use fallback message
                state_str = str(state)
                logging.info(f"State: {state_str}")
                error_message = falldown_smalltalk_response(state_str)

            # Ensure error message is user-friendly (not technical)
            if any(
                term in error_message
                for term in ["Error:", "Exception:", "Traceback", "redis", "Redis"]
            ):
                state_str = str(state)
                logging.info(f"State: {state_str}")
                error_message = falldown_smalltalk_response(state_str)

        await send_whatsapp_message_back(error_message, sender)
        logger.info(f"Error response sent to {sender}: {error_message[:100]}...")

        if not has_location_data:
            # Update state for regular errors
            state["status"] = "error"

            # Clear error flags to prevent persistence - THIS IS CRUCIAL
            state["error"] = False  # Clear the error flag

            # Only clean up state if this is NOT a location data request for add_project_gps
            current_intent = state.get("current_intent", "")
            should_preserve_state = current_intent == "add_project_gps" and (
                "位置資料" in error_message
                or "位置" in error_message
                or "location" in error_message.lower()
            )

            if not should_preserve_state:
                # Attempt to clean up any problematic state for regular errors
                redis_healthy = not state.get("redis_unhealthy", False)
                if redis_healthy:
                    await _safe_cleanup_conversation_state(sender)
            else:
                # For location data requests, preserve the state but save it
                redis_healthy = not state.get("redis_unhealthy", False)
                if redis_healthy:
                    from infrastructure.redis_connection.redis_manager import save_state

                    await save_state(sender, state)
                    logging.info(
                        f"Preserved conversation state for {sender} while waiting for location data"
                    )

        return state

    except Exception as e:
        logger.error(f"Error in error response handler: {str(e)}", exc_info=True)
        # Fallback error message
        await send_whatsapp_message_back(
            "⚠️ An error occurred. Please try again.", sender
        )
        state["error"] = False  # Clear error flag even in fallback
        return state


async def _handle_image_collection_response(
    state: Dict[str, Any], sender: str
) -> Dict[str, Any]:
    """Handle image collection in progress response with Chinese messages"""
    try:
        image_count = state.get("image_count", 0) or len(state.get("media_urls", []))
        current_intent = state.get("current_intent", "")

        if state.get("status") == "collecting_images":
            response_message = f"\n{image_count}張卡已經處理緊，請繼續提供卡嘅圖片，我會幫你哋處理👍。\n如果唔想繼續提供，可以講『done』或者『完成』"
        else:
            response_message = "AI而家仲喺開發緊，撞到啲小問題😅麻煩你搵下管理員幫手啦～我哋會慢慢學多啲嘢，希望之後可以幫到你更多～😉真係唔該晒你體諒呀 🙏"

        await send_whatsapp_message_back(response_message, sender)
        logger.info(
            f"Image collection response sent to {sender} for {image_count} images"
        )

        # Update state
        state["action_result"] = response_message

        return state

    except Exception as e:
        logger.error(
            f"Error in image collection response handler: {str(e)}", exc_info=True
        )
        # Fallback message (keeping original Chinese)
        await send_whatsapp_message_back(
            "AI而家仲喺開發緊，撞到啲小問題😅麻煩你搵下管理員幫手啦～我哋會慢慢學多啲嘢，希望之後可以幫到你更多～😉真係唔該晒你體諒呀 🙏",
            sender,
        )
        return state


async def _handle_await_field_response(
    state: Dict[str, Any], sender: str
) -> Dict[str, Any]:
    """Handle awaiting more information response"""
    try:
        field_message = state.get("action_result", "")

        # Handle both string and dict responses
        if isinstance(field_message, dict):
            # Extract message from dict response
            field_message = field_message.get("message", "")

        # Provide helpful default message if none exists
        if not field_message or (isinstance(field_message, str) and field_message.strip() == ""):
            field_message = "I need more information to help you. Could you please provide additional details?"

        await send_whatsapp_message_back(field_message, sender)
        logger.info(f"Field request sent to {sender}: {field_message[:100]}...")

        # Update state

        return state

    except Exception as e:
        logger.error(f"Error in await field response handler: {str(e)}", exc_info=True)
        # Fallback message
        await send_whatsapp_message_back(
            "I need more information to proceed. Please provide additional details.",
            sender,
        )
        return state


async def _handle_critical_error(
    state: Dict[str, Any], error: Exception
) -> Dict[str, Any]:
    """Handle critical errors in the case_completed node itself"""
    try:
        sender = _extract_sender(state)
        if sender:
            # Use original Chinese error message
            await send_whatsapp_message_back("⚠️ 系統錯誤。請重試。", sender)
            logger.info(f"Critical error fallback message sent to {sender}")

        # Don't persist the error - clear it after handling
        state["error"] = False  # Clear error flag to prevent persistence
        state["status"] = (
            "error_handled"  # Use different status to indicate it was handled
        )
        state["action_result"] = "系統錯誤。請重試。"

        # Attempt cleanup if possible
        if sender:
            await _safe_cleanup_conversation_state(sender)

    except Exception as fallback_error:
        logger.error(f"Even critical error handler failed: {str(fallback_error)}")
        # Last resort - make sure we don't persist errors
        state["error"] = False

    return state


async def _safe_cleanup_conversation_state(sender: str) -> bool:
    """
    Safely clean up conversation state with proper error isolation.
    Returns True if cleanup succeeded, False if it failed.
    """
    try:
        # Set a reasonable timeout for cleanup operations
        cleanup_timeout = 5.0  # 5 seconds

        # Attempt cleanup with timeout
        await asyncio.wait_for(_perform_cleanup(sender), timeout=cleanup_timeout)
        logger.info(f"Cleanup completed successfully for {sender}")
        return True

    except asyncio.TimeoutError:
        logger.warning(f"Cleanup timed out for {sender} after {cleanup_timeout}s")
        return False
    except Exception as cleanup_error:
        logger.warning(f"Cleanup failed for {sender}: {str(cleanup_error)}")
        return False


async def _perform_cleanup(sender: str) -> None:
    """Perform the actual cleanup operations for wls-assistant project"""
    try:
        # Clear conversation state
        await clear_state(sender)
        logger.debug(f"Conversation state cleared for {sender}")

        # Clear image collection
        await clear_image_collection(sender)
        logger.debug(f"Image collection cleared for {sender}")

        # Clear any additional Redis keys for this sender (wls-assistant specific)
        async with redis_manager.get_client() as client:
            pattern = f"{redis_key_prefix}:*:{sender}"
            keys = await client.keys(pattern)

            if keys:
                deleted_count = await client.delete(*keys)
                logger.debug(
                    f"Cleared {deleted_count} additional Redis keys for {sender}"
                )
            else:
                logger.debug(f"No additional Redis keys found for {sender}")

    except Exception as e:
        logger.warning(f"Error during cleanup operations for {sender}: {str(e)}")
        raise  # Re-raise to be caught by timeout wrapper
