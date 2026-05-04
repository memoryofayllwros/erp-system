"""
Enhanced LangGraph Agent with Intelligent State Management and Intent Routing
This agent provides robust handling of conversation flows, intent transitions, and state cleanup.
"""

import logging
from typing import Any, Dict
from src.chatbot_service.chatbot_helpers.intent_manager import (
    SIMPLE_READ_INTENTS
)
from langgraph.graph import END, StateGraph

from src.chatbot_service.langgraph.nodes.human_confirmation import \
    human_confirmation_node
from src.chatbot_service.langgraph.nodes.step0_image_collection import \
    image_collection_node
from src.chatbot_service.langgraph.nodes.step1_intent_classifier import \
    intent_classifier_node
from src.chatbot_service.langgraph.nodes.step2_document_validation import \
    document_validation_node
from src.chatbot_service.langgraph.nodes.step3_entity_extraction import \
    entity_extraction_node
from src.chatbot_service.langgraph.nodes.step4_entity_validation import \
    entity_validation_node
from src.chatbot_service.langgraph.nodes.step5_NoSQL_execution import \
    NoSQL_execution_node
from src.chatbot_service.langgraph.nodes.step6_case_completed import \
    case_completed_node
from src.chatbot_service.langgraph.state import WorkflowState
from infrastructure.redis_connection.redis_manager import is_collection_ready_for_processing

# Configure logger
logger = logging.getLogger(__name__)


async def check_in_image_link_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate and send image check-in link based on attendance status"""
    logger = logging.getLogger(__name__)
    logger.info("Checkin image link node: Generating and sending image check-in link")

    try:
        # Extract sender information
        user_messages = [
            m for m in state.get("messages", []) if m.get("role") == "user"
        ]
        if not user_messages:
            logger.error("No user messages found in state")
            state["error"] = True
            state["action_result"] = "無法識別用戶信息"
            return state

        sender = user_messages[-1].get("content", {}).get("From", "")

        from src.models.attendance_record_model import AttendanceRecord

        attendance_info = await AttendanceRecord.get_attendance_info(
            sender, link_type="image"
        )
        logging.info(f"attendance_info in check_in_image_link_node: {attendance_info}")

        attendance_status = attendance_info.get("attendance_status", "")
        logging.info(
            f"attendance_status in check_in_image_link_node: {attendance_status}"
        )

        # Get the message and data from attendance_info
        response_message = attendance_info.get("message", "")
        attendance_data = attendance_info.get("data", {})

        # Handle different attendance statuses intelligently
        if attendance_status == "no_record":
            # Worker hasn't started work today
            logger.info(
                f"Worker {sender} has no attendance record - sending image check-in link"
            )

            # Generate image check-in link
            from src.routes.attendance_via_image_routes import \
                generate_image_attendance_link

            checkin_link = await generate_image_attendance_link(sender)

            state["action_result"] = (
                f"{response_message}\n\n📷 Special work check-in link: \n{checkin_link}"
            )
            state["status"] = "success"
            state["next_action"] = "check_in_image"

        elif attendance_status in [
            "morning_checked_in",
            "afternoon_checked_in",
            "both_shifts_checked_in",
        ]:
            # Worker has checked in but not completed work
            logger.info(
                f"Worker {sender} has checked in - sending image check-out link"
            )

            # Generate image check-in link (can be used for check-out too)
            from src.routes.attendance_via_image_routes import \
                generate_image_attendance_link

            checkin_link = await generate_image_attendance_link(sender)

            state["action_result"] = (
                f"{response_message}\n\n📷 Special work check-out link: \n{checkin_link}"
            )
            state["status"] = "success"
            state["next_action"] = "check_out_image"

        elif attendance_status == "partial_completion":
            # Worker has completed some shifts but has pending work
            logger.info(
                f"Worker {sender} has partial completion - sending image check-in link for remaining work"
            )

            # Generate image check-in link
            from src.routes.attendance_via_image_routes import \
                generate_image_attendance_link

            checkin_link = await generate_image_attendance_link(sender)

            state["action_result"] = (
                f"{response_message}\n\n📷 Special work check-in link / 特殊打卡簽到連結: \n{checkin_link}"
            )
            state["status"] = "success"
            state["next_action"] = "additional_work_image"

        elif attendance_status in [
            "morning_completed",
            "afternoon_completed",
            "all_shifts_completed",
            "shift_completed",
        ]:
            # Worker has completed their shifts
            logger.info(f"Worker {sender} has completed work - no action needed")
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "completed"

        elif attendance_status == "checked_in_pending":

            from src.routes.attendance_via_image_routes import \
                generate_image_attendance_link

            checkin_link = await generate_image_attendance_link(sender)

            state["action_result"] = (
                f"{response_message}\n\n📷 Special check-out link / 特殊簽退連結: \n{checkin_link}"
            )
            state["status"] = "success"
            state["next_action"] = "check_out_image"

        elif attendance_status == "partial_day":
            from src.routes.attendance_via_image_routes import \
                generate_image_attendance_link

            checkin_link = await generate_image_attendance_link(sender)

            state["action_result"] = (
                f"{response_message}\n\n📷 Special check-in link / 特殊簽到連結: \n{checkin_link}"
            )
            state["status"] = "success"
            state["next_action"] = "additional_work_image"

        elif attendance_status == "full_day_completed":
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "completed"

        elif attendance_status == "anomalous_activity":
            state["error"] = True
            state["action_result"] = (
                f"Anomalous activity detected: {response_message}\n\nPlease contact the administrator to confirm your attendance record."
            )
            return state

        elif attendance_status == "incomplete_shift":
            state["error"] = True
            state["action_result"] = (
                f"Incomplete shift detected: {response_message}\n\nPlease contact the administrator to process."
            )
            return state

        elif attendance_status == "error":
            # Error occurred in attendance processing
            logger.error(
                f"Error in attendance processing for {sender}: {response_message}"
            )
            state["error"] = True
            state["action_result"] = f"System error: {response_message}"
            return state

        else:
            # Unknown status - log and provide generic response
            logger.warning(
                f"Unknown attendance status '{attendance_status}' for {sender}"
            )
            state["error"] = True
            state["action_result"] = "Unable to determine your attendance status, please contact the administrator"
            return state

        # Log detailed attendance information for debugging
        if attendance_data:
            logger.info(f"Detailed attendance data for {sender}:")
            analysis = attendance_data.get("analysis", {})
            if analysis:
                projects = analysis.get("projects", [])
                logger.info(f"  Projects: {len(projects)}")
                for project in projects:
                    project_code = project.get("project_code", "Unknown")
                    shifts = project.get("shifts", [])
                    logger.info(f"  - Project {project_code}: {len(shifts)} shifts")
                    for shift in shifts:
                        shift_type = shift.get("shift_type", "Unknown")
                        checked_in = shift.get("checked_in", False)
                        checked_out = shift.get("checked_out", False)
                        logger.info(
                            f"    - {shift_type}: checked_in={checked_in}, checked_out={checked_out}"
                        )

        # Log final status and any warnings 
        if (
            state.get("next_action") in ["check_out_image", "additional_work_image"]
            and attendance_data
        ):
            # Check if worker has been working for too long without checking out
            analysis = attendance_data.get("analysis", {})
            if analysis:
                projects = analysis.get("projects", [])
                for project in projects:
                    shifts = project.get("shifts", [])
                    for shift in shifts:
                        if shift.get("checked_in") and not shift.get("checked_out"):
                            check_in_time = shift.get("check_in_time")
                            if check_in_time:
                                logger.info(
                                    f"Worker {sender} checked in at {check_in_time} and needs to check out"
                                )

        logger.info(
            f"Image check-in link node completed for {sender}: {attendance_status}"
        )
        return state

    except Exception as e:
        logger.error(f"Error in check_in_image_link_node: {str(e)}", exc_info=True)
        state["error"] = True
        state["action_result"] = "Error generating image check-in link, please try again later"
        return state


async def check_in_gps_link_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate and send check-in link based on attendance status"""
    logger = logging.getLogger(__name__)
    logger.info("Checkin link node: Generating and sending check-in link")

    try:
        # Extract sender information
        user_messages = [
            m for m in state.get("messages", []) if m.get("role") == "user"
        ]
        if not user_messages:
            logger.error("No user messages found in state")
            state["error"] = True
            state["action_result"] = "Unable to identify user information"
            return state

        sender = user_messages[-1].get("content", {}).get("From", "")

        from src.models.attendance_record_model import AttendanceRecord

        attendance_info = await AttendanceRecord.get_attendance_info(sender)
        logging.info(f"attendance_info in check_in_link_node: {attendance_info}")

        attendance_status = attendance_info.get("attendance_status", "")
        logging.info(f"attendance_status in check_in_link_node: {attendance_status}")

        # Get the message and data from attendance_info
        response_message = attendance_info.get("message", "")
        attendance_data = attendance_info.get("data", {})

        # Handle different attendance statuses intelligently
        if attendance_status == "no_record":
            # Worker hasn't started work today
            logger.info(
                f"Worker {sender} has no attendance record - sending check-in link"
            )
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "check_in"

        elif attendance_status in [
            "morning_checked_in",
            "afternoon_checked_in",
            "both_shifts_checked_in",
        ]:
            # Worker has checked in but not completed work
            logger.info(f"Worker {sender} has checked in - sending check-out link")
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "check_out"

        elif attendance_status in [
            "morning_completed",
            "afternoon_completed",
            "all_shifts_completed",
        ]:
            # Worker has completed their shifts
            logger.info(f"Worker {sender} has completed work - no action needed")
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "completed"

        elif attendance_status == "partial_completion":
            # Worker has completed some shifts but has pending work
            logger.info(
                f"Worker {sender} has partial completion - sending check-in link for remaining work"
            )
            state["action_result"] = response_message
            state["status"] = "success"
            state["next_action"] = "additional_work"

        elif attendance_status == "error":
            # Error occurred in attendance processing
            logger.error(
                f"Error in attendance processing for {sender}: {response_message}"
            )
            state["error"] = True
            state["action_result"] = f"System error: {response_message}"
            return state

        else:
            # Unknown status - log and provide generic response
            logger.warning(
                f"Unknown attendance status '{attendance_status}' for {sender}"
            )
            if response_message:
                state["action_result"] = response_message
            else:
                state["action_result"] = "Unable to determine your current attendance status, please contact the administrator"
            state["status"] = "success"
            state["next_action"] = "unknown"

        # Add additional context to the response if available
        if attendance_data and not state.get("error"):
            # Extract useful information for logging and potential use by other nodes
            next_action = attendance_data.get("next_action", "")
            has_pending_work = attendance_data.get("has_pending_work", False)
            completed_shifts = attendance_data.get("completed_shifts", 0)
            total_ot_hours = attendance_data.get("total_ot_hours", 0.0)

            # Store useful data in state for potential use by other nodes
            state["attendance_summary"] = {
                "next_action": next_action,
                "has_pending_work": has_pending_work,
                "completed_shifts": completed_shifts,
                "total_ot_hours": total_ot_hours,
                "attendance_status": attendance_status,
            }

            logger.info(
                f"Worker {sender} - Next action: {next_action}, Pending work: {has_pending_work}, "
                f"Completed shifts: {completed_shifts}, OT hours: {total_ot_hours}"
            )

            # If there's analysis data, log summary for monitoring and store in state
            analysis = attendance_data.get("analysis", {})
            if analysis:
                overall_summary = analysis.get("overall_summary", {})
                total_shifts = overall_summary.get("total_shifts", 0)
                pending_check_outs = overall_summary.get("pending_check_outs", 0)

                # Store analysis data in state
                state["attendance_analysis"] = {
                    "total_shifts": total_shifts,
                    "pending_check_outs": pending_check_outs,
                    "projects": analysis.get("projects", []),
                }

                logger.info(
                    f"Attendance summary for {sender}: Total shifts: {total_shifts}, "
                    f"Pending checkouts: {pending_check_outs}"
                )

                # Log project-specific information if available
                projects = analysis.get("projects", [])
                for project in projects:
                    project_title = project.get("project_title", "Unknown Project")
                    shifts = project.get("shifts", [])
                    logger.info(f"Project {project_title}: {len(shifts)} shifts")
                    for shift in shifts:
                        shift_type = shift.get("shift_type", "unknown")
                        checked_in = shift.get("checked_in", False)
                        checked_out = shift.get("checked_out", False)
                        logger.info(
                            f"  - {shift_type}: checked_in={checked_in}, checked_out={checked_out}"
                        )

        # Log final status and any warnings
        if state.get("next_action") == "check_out" and attendance_data:
            # Check if worker has been working for too long without checking out
            analysis = attendance_data.get("analysis", {})
            if analysis:
                projects = analysis.get("projects", [])
                for project in projects:
                    shifts = project.get("shifts", [])
                    for shift in shifts:
                        if shift.get("checked_in") and not shift.get("checked_out"):
                            check_in_time = shift.get("check_in_time")
                            if check_in_time:
                                logger.info(
                                    f"Worker {sender} checked in at {check_in_time} and needs to check out"
                                )

        logger.info(f"Check-in link node completed for {sender}: {attendance_status}")
        return state

    except Exception as e:
        logger.error(f"Error in check_in_link_node: {str(e)}", exc_info=True)
        state["error"] = True
        state["action_result"] = "Error generating check-in link, please try again later"
        return state


# --- INTENT DEFINITIONS AND ROUTING LOGIC ---


# Read intents that don't need entity extraction (can go directly to execution)



# --- ENHANCED ROUTING FUNCTIONS ---


def is_simple_read_intent(state: Dict[str, Any]) -> bool:
    """Check if current intent is a simple read-only operation that doesn't need entity extraction"""
    current_intent = state.get("current_intent", "")
    if current_intent in SIMPLE_READ_INTENTS:
        state["validated"] = True
        state["error"] = False
        state["status"] = "slot_filled"
        return True
    return False


# CONVERSATION FLOW CONTROL - Determines next step after response


# CONVERSATION FLOW CONTROL - Determines next step after response
async def image_collector_condition(state: Dict[str, Any]) -> str:
    from infrastructure.redis_connection.redis_manager import get_image_collection

    """Enhanced routing from image collector with better temporal workflow coordination"""
    try:
        status = state.get("status", "")
        messages = state.get("messages", [])
        logger.info(
            f"image_collector_condition: status='{status}', has_messages={len(messages)}"
        )

        if (
            not messages
            or "content" not in messages[-1]
            or "From" not in messages[-1]["content"]
        ):
            logger.error("No sender found in state messages")
            return "intent_classifier"
        sender = messages[-1]["content"]["From"]
        state["collection_timeout_seconds"] = 30

        has_media = False
        media_url = None

        # Check MediaUrl0 in the latest message
        current_message = messages[-1]["content"]
        media_url = current_message.get("MediaUrl0")
        body = current_message.get("Body", "").lower().strip()

        # Check if this is a "done" command - but DON'T modify state here
        is_done_command = body in ["done", "end", "完成"]

        if is_done_command:
            logger.info(
                "Done command detected in condition - routing based on current state"
            )
            # The actual state modification happens in image_collection_node
            # Here we just route based on the done_command_received flag that was set there
            if state.get("done_command_received", True):
                logger.info(
                    "Done command was processed by image_collection_node, routing to intent classifier"
                )
                return "intent_classifier"
            else:
                logger.warning(
                    "Done command detected but flag not set - may need to process through collector first"
                )
                return "responder"

        else:  # if not done command, continue with normal flow
            original_body = state.get("original_body", "")

            # Also check media_urls in state (this is populated from main.py)
            state_media_urls = state.get("media_urls", [])

            if media_url or state_media_urls:
                has_media = True
                logger.info(
                    f"Media detected: MediaUrl0={bool(media_url)}, state_media_urls={len(state_media_urls)}"
                )

                # If we're not already collecting images, set the state
                if status != "collecting_images":
                    state["status"] = "collecting_images"
                    state["image_collection_active"] = True
                    state["image_collection_processed"] = False
                    logger.info(
                        f"Setting state to collecting_images due to media detection"
                    )

            # Get any existing collection from Redis
            collection = await get_image_collection(sender)
            if collection and collection.get("images"):
                collection_images = collection.get("images", [])
                logger.info(
                    f"Found existing collection with {len(collection_images)} images"
                )

                # Use the deduplication function from redis_manager for consistent handling
                from infrastructure.redis_connection.redis_manager import redis_manager

                unique_images = redis_manager.deduplicate_media_urls(collection_images)

                # Only update state if we have unique images
                if unique_images:
                    state["media_urls"] = unique_images
                    state["image_count"] = len(unique_images)
                    state["collected_image_count"] = len(unique_images)
                    logger.info(
                        f"Synced {len(unique_images)} unique images from Redis to state (was {len(collection_images)} total)"
                    )

                    collection_body = collection.get("original_body", "")
                    if collection_body and (
                        not original_body or "project" in collection_body.lower()
                    ):
                        state["original_body"] = collection_body
                        original_body = collection_body
                        logger.info(
                            f"Synced original body from collection: {collection_body}"
                        )
            elif state_media_urls:
                # Use the deduplication function for consistent handling
                from infrastructure.redis_connection.redis_manager import redis_manager

                unique_state_urls = redis_manager.deduplicate_media_urls(
                    state_media_urls
                )

                state["media_urls"] = unique_state_urls
                state["image_count"] = len(unique_state_urls)
                state["collected_image_count"] = len(unique_state_urls)
                logger.info(
                    f"Using {len(unique_state_urls)} unique media URLs from state (was {len(state_media_urls)} total)"
                )
            else:
                state["media_urls"] = []
                state["image_count"] = 0
                state["collected_image_count"] = 0

            if status == "collecting_images":
                logger.info(
                    "Status is collecting_images, routing to image collector for proper handling"
                )

                # Don't mark as processed yet - let the image_collection_node handle this
                # state["image_collection_processed"] = True
                # state["image_collection_active"] = False

                if original_body:
                    if messages and len(messages) > 0:
                        current_message = messages[-1]["content"]
                        current_body = current_message.get("Body", "")
                        if current_body.lower().strip() in ["done", "end"]:
                            current_message["Body"] = original_body
                            logger.info(
                                f"Enhanced message with original body for intent classification: {original_body}"
                            )

                # Route to image collector node instead of responder to prevent premature cleanup
                return "image_collection"

            is_ready = await is_collection_ready_for_processing(
                sender, state["collection_timeout_seconds"]
            )
            logger.info(f"Collection ready check: is_ready={is_ready}")

            if is_ready:
                logger.info(
                    f"Collection timeout passed ({state['collection_timeout_seconds']}s), routing to intent classifier"
                )

                latest_collection = await get_image_collection(sender)
                if latest_collection and latest_collection.get("images"):
                    # Use the deduplication function from redis_manager for consistent handling
                    from infrastructure.redis_connection.redis_manager import redis_manager

                    latest_images = latest_collection.get("images", [])
                    unique_latest_images = redis_manager.deduplicate_media_urls(
                        latest_images
                    )

                    state["media_urls"] = unique_latest_images
                    state["image_count"] = len(unique_latest_images)
                    state["collected_image_count"] = len(unique_latest_images)
                    logger.info(
                        f"Final sync: {len(unique_latest_images)} unique images from Redis to state (was {len(latest_images)} total)"
                    )

                    collection_body = latest_collection.get("original_body", "")
                    if collection_body and (
                        not original_body or "project" in collection_body.lower()
                    ):
                        state["original_body"] = collection_body
                        original_body = collection_body

                state["image_collection_processed"] = True
                state["image_collection_active"] = False
                state["status"] = "await_intent"

                if messages and len(messages) > 0 and original_body:
                    current_message = messages[-1]["content"]
                    current_body = current_message.get("Body", "")
                    current_message["Body"] = original_body
                    logger.info(
                        f"Enhanced message with original body for intent classification: {original_body}"
                    )

                return "intent_classifier"

            if (
                has_media
                and state["status"] == "collecting_images"
                and not state.get("message_sent", False)
            ):
                logger.info(
                    f"Active image collection with {state.get('image_count', 0)} images, routing to responder for response"
                )
                # Mark that we're about to send a response to prevent loops
                state["message_sent"] = True
                return "responder"

            if has_media and state.get("image_collection_active") != True:
                logger.info(f"Starting new image collection with media")
                state["image_collection_active"] = True
                state["image_collection_processed"] = False
                state["status"] = "collecting_images"
                state["message_sent"] = False  # Reset message sent flag
                return "responder"

            logger.info(
                "No active image collection needed, proceeding to intent classification"
            )
            state["status"] = "await_intent"
            return "intent_classifier"

    except Exception as e:
        logger.error(f"Error in image_collector_condition: {str(e)}", exc_info=True)
        return "intent_classifier"


# CONVERSATION FLOW CONTROL - Determines next step after response
async def intent_classifier_condition(state: Dict[str, Any]) -> str:
    """Enhanced intent classification routing with validation and state management"""
    try:
        status = state.get("status", "")
        current_intent = state.get("current_intent", "")

        # Special handling for add_unprocessed_cards intent that's waiting for more images
        if current_intent == "add_unprocessed_cards" and status == "await_intent":
            logger.info(
                f"add_unprocessed_cards intent in await_intent status, routing back to image collector"
            )
            return "image_collection"

        if status == "await_field" or status == "intent_detected":
            logger.info("Continuing previous conversation, routing to entity extractor")
            return "entity_extractor"

        if current_intent == "check_in_via_gps":
            logger.info("Routing check_in_via_gps to check_in_gps_link node")
            return "check_in_gps_link"

        if current_intent == "check_in_via_image":
            logger.info("Routing check_in_via_image to check_in_image_link node")
            return "check_in_image_link"

        if is_simple_read_intent(state):
            logger.info(
                f"Simple read intent '{current_intent}' detected, routing to execution"
            )
            return "execute_function"

        logger.info(f"Intent '{current_intent}' requires entity extraction")
        return "entity_extractor"

    except Exception as e:
        logger.error(f"Error in intent_classifier_condition: {str(e)}")
        return "entity_extractor"


# CONVERSATION FLOW CONTROL - Determines next step after response
async def entity_extraction_condition(state: Dict[str, Any]) -> str:
    """Enhanced entity extraction routing with better error handling"""
    try:
        error = state.get("error", False)
        validated = state.get("validated", False)
        current_intent = state.get("current_intent", "")

        # Check if we have location data that should be handled specially
        has_location_data = False
        if state.get("messages") and len(state.get("messages", [])) > 0:
            latest_message = state["messages"][-1].get("content", {})
            has_location_data = latest_message.get("Latitude") and latest_message.get(
                "Longitude"
            )

        if error:
            # If we have location data, let step6 handle it properly instead of routing to responder
            if has_location_data:
                logger.info(
                    f"Error detected but location data present, routing to case_completed for proper handling"
                )
                return "case_completed"
            else:
                logger.info(
                    f"Error detected in state (validated={validated}), routing to responder"
                )
                return "responder"

        logger.info(
            f"Entity extraction completed for '{current_intent}', routing to validation"
        )
        return "entity_validation"

    except Exception as e:
        logger.error(f"Error in entity_extraction_condition: {str(e)}")
        # Route to responder on exception
        state["error"] = True
        state["action_result"] = "系統錯誤，請稍後再試"
        return "responder"


# CONVERSATION FLOW CONTROL - Determines next step after response
async def entity_validation_condition(state: Dict[str, Any]) -> str:
    """Enhanced validation routing with better decision logic"""
    try:
        error = state.get("error", False)
        status = state.get("status", "")
        current_intent = state.get("current_intent", "")

        if error:
            logger.info(
                f"Validation error for intent '{current_intent}', routing to responder"
            )
            return "responder"

        if status == "slot_filled":
            logger.info(
                f"Validation successful for intent '{current_intent}', routing to execution"
            )
            return "NoSQL_execution"

        logger.info(
            f"Validation incomplete for intent '{current_intent}' (status: {status}), routing to responder"
        )
        return "responder"

    except Exception as e:
        logger.error(f"Error in entity_validation_condition: {str(e)}")
        return "responder"


def checkin_link_condition(state: Dict[str, Any]) -> str:
    """Check if the workflow should end or continue after sending a response"""
    try:
        current_intent = state.get("current_intent", "")

        if current_intent == "check_in_via_gps":
            logger.info("Routing to checkin link condition")
            return "check_in_gps_link"

        if current_intent == "check_in_via_image":
            logger.info("Routing to checkin image link condition")
            return "check_in_image_link"

        return "responder"

    except Exception as e:
        logger.error(f"Error in checkin_link_condition: {str(e)}")
        return "responder"


# --- BUILD THE ENHANCED GRAPH ---

graph = StateGraph(state_schema=WorkflowState)

# Add all nodes
graph.add_node("image_collection", image_collection_node)
graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("document_validation", document_validation_node)
graph.add_node("entity_extraction", entity_extraction_node)
graph.add_node("entity_validation", entity_validation_node)
graph.add_node("NoSQL_execution", NoSQL_execution_node)
graph.add_node("case_completed", case_completed_node)
graph.add_node("responder", case_completed_node)
graph.add_node("check_in_gps_link", check_in_gps_link_node)
graph.add_node("check_in_image_link", check_in_image_link_node)
graph.add_node("human_confirmation", human_confirmation_node)

graph.set_entry_point("image_collection")


def image_collector_router(state: Dict[str, Any]) -> str:
    """Router for image collector node"""
    try:
        status = state.get("status", "")
        if status == "collecting_images":
            logger.info("Routing to image collector for collecting images")
            return "responder"
        else:
            logger.info("Routing to responder - need more information")
            return "intent_classifier"
    except Exception as e:
        logger.error(f"Error in image_collector_router: {str(e)}")
        return "intent_classifier"


graph.add_conditional_edges(
    "image_collection",
    image_collector_router,
    {
        "intent_classifier": "intent_classifier",  # 1. Move to intent classification, 2. (for done/timeout scenarios) ->move to intent classification
        "responder": "responder",  # Send collection response
        "end": END,  # End workflow (for done/timeout scenarios)
    },
)


# Intent classifier routing
def intent_classifier_router(state):
    """Router for intent classifier node"""
    try:
        status = state.get("status", "")
        current_intent = state.get("current_intent", "")

        if current_intent == "check_in_via_gps":
            logger.info("Routing check_in_via_gps to check_in_gps_link node")
            return "check_in_gps_link"

        elif current_intent == "check_in_via_image":
            logger.info("Routing check_in_via_image to check_in_image_link node")
            return "check_in_image_link"

        elif is_simple_read_intent(state):
            logger.info("Routing to NoSQL execution for simple read intent")
            return "NoSQL_execution"

        else:
            logger.info("Routing to document validation")
            return "document_validation"

    except Exception as e:
        logger.error(f"Error in intent_classifier_router: {str(e)}")
        return "document_validation"


graph.add_conditional_edges(
    "intent_classifier",
    intent_classifier_router,
    {
        "document_validation": "document_validation",
        "NoSQL_execution": "NoSQL_execution",
        "check_in_gps_link": "check_in_gps_link",
        "check_in_image_link": "check_in_image_link",
    },
)

# Checkin link always goes to responder after sending the link
graph.add_edge("check_in_gps_link", "responder")
graph.add_edge("check_in_image_link", "responder")


def document_validation_router(state):
    """Router for document validation node"""
    try:
        status = state.get("status", "")
        if status == "await_document_validation":
            logger.info("Routing to entity extractor for document validation")
            return "entity_extraction"
        else:
            logger.info("Routing to responder - need more information")
            return "entity_extraction"
    except Exception as e:
        logger.error(f"Error in document_validation_router: {str(e)}")
        return "entity_extraction"


graph.add_conditional_edges(
    "document_validation",
    document_validation_router,
    {"entity_extraction": "entity_extraction", "responder": "responder"},
)


# Entity extraction routing
def entity_extraction_router(state):
    """Router for entity extractor node"""
    try:
        error = state.get("error", False)

        if error:
            logger.info("Routing to responder due to extraction error")
            return "responder"
        else:
            logger.info("Routing to entity validation for validation")
            return "entity_validation"

    except Exception as e:
        logger.error(f"Error in entity_extraction_router: {str(e)}")
        # Set error state and route to responder
        state["error"] = True
        state["action_result"] = "系統錯誤，請稍後再試"
        return "responder"


graph.add_conditional_edges(
    "entity_extraction",
    entity_extraction_router,
    {"responder": "responder", "entity_validation": "entity_validation"},
)


# Validation function routing
def entity_validation_router(state):
    """Router for validation function node"""
    try:
        error = state.get("error", False)
        status = state.get("status", "")

        # Check if human confirmation is required
        import asyncio

        from src.chatbot_service.langgraph.nodes.human_confirmation import \
            whether_requiring_human_confirmation

        requires_confirmation = asyncio.run(whether_requiring_human_confirmation(state))

        if error:
            logger.info("Routing to responder due to validation error")
            return "responder"
        elif requires_confirmation:
            logger.info("Routing to human confirmation - confirmation required")
            state["status"] = "await_human_confirmation"
            return "human_confirmation"
        elif status == "slot_filled":
            logger.info("Routing to NoSQL execution - slots filled")
            return "NoSQL_execution"
        else:
            logger.info("Routing to responder - need more information")
            return "responder"

    except Exception as e:
        logger.error(f"Error in entity_validation_router: {str(e)}")
        return "responder"


graph.add_conditional_edges(
    "entity_validation",
    entity_validation_router,
    {
        "responder": "responder",
        "NoSQL_execution": "NoSQL_execution",
        "human_confirmation": "human_confirmation",
    },
)

# Execution always goes to responder for final response
graph.add_edge("NoSQL_execution", "responder")


# Human confirmation routing
def human_confirmation_router(state):
    """Router for human confirmation node"""
    try:
        status = state.get("status", "")
        human_confirmation_received = state.get("human_confirmation_received", False)

        if status == "slot_filled" and human_confirmation_received:
            logger.info("Human confirmation received, routing to NoSQL execution")
            return "NoSQL_execution"
        elif status == "await_intent":
            logger.info("Human confirmation rejected, routing to intent classifier")
            return "intent_classifier"
        else:
            logger.info("Awaiting human confirmation, routing to responder")
            return "responder"

    except Exception as e:
        logger.error(f"Error in human_confirmation_router: {str(e)}")
        return "responder"


graph.add_conditional_edges(
    "human_confirmation",
    human_confirmation_router,
    {
        "responder": "responder",
        "NoSQL_execution": "NoSQL_execution",
        "intent_classifier": "intent_classifier",
    },
)


# Add responder conditional edge to handle image collection responses
async def responder_condition(state: Dict[str, Any]) -> str:
    """Determine if the workflow should end or continue after sending a response"""
    try:
        status = state.get("status", "")

        # If we're waiting for human confirmation, don't end the workflow
        if status == "await_human_confirmation":
            logger.info("Continuing workflow to await human confirmation")
            return "human_confirmation"
        elif status == "success":
            logger.info("Ending workflow after successful response")
            return "end"
        else:
            logger.info("Ending workflow after response")
            return "end"

    except Exception as e:
        logger.error(f"Error in responder_condition: {str(e)}")
        return "end"


# Responder can end the workflow or route to human confirmation
graph.add_conditional_edges(
    "responder",
    responder_condition,
    {"end": END, "human_confirmation": "human_confirmation"},
)

# Compile the graph
compiled_graph = graph.compile()

logger.info(
    "Enhanced LangGraph agent compiled successfully with intelligent routing and state management"
)
