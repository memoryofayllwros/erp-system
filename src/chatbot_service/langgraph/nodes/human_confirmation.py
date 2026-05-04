import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from src.chatbot_service.llm_prompts.boolean_prompts import \
    boolean_value_response
from src.utils.datetime_standarization_helpers import get_this_moment, HK_TZ
from src.chatbot_service.llm_prompts.project_prompts import add_project_gps_response
from infrastructure.redis_connection.redis_manager import redis_manager, save_state

key_name = os.getenv("KEY_NAME")


# Helper functions for location data management
async def store_location_data(
    sender: str,
    latitude: str,
    longitude: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Store location data in Redis with improved metadata and error handling

    Args:
        sender: The sender's identifier (usually phone number)
        latitude: The latitude value
        longitude: The longitude value
        metadata: Optional additional metadata to store with the location

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create location data with metadata
        location_data = {
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": get_this_moment().isoformat(),
            "intent": "add_project_gps",
            "stored_at": get_this_moment().isoformat(),
        }

        # Add any additional metadata
        if metadata:
            location_data.update(metadata)

        key = f"{key_name}:location_data:{sender}"
        async with redis_manager.get_client() as client:
            # Store for 2 hours (7200 seconds) to give users more time to complete the workflow
            await client.setex(key, 7200, json.dumps(location_data))

        logging.info(f"Stored location data in Redis for {sender}: {location_data}")
        return True

    except Exception as e:
        logging.error(f"Error storing location data in Redis: {str(e)}", exc_info=True)
        return False


async def retrieve_location_data(
    sender: str, delete_after_retrieval: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Retrieve location data from Redis with error handling

    Args:
        sender: The sender's identifier (usually phone number)
        delete_after_retrieval: Whether to delete the data after retrieving it

    Returns:
        Optional[Dict[str, Any]]: The location data if found, None otherwise
    """
    try:
        key = f"{key_name}:location_data:{sender}"
        async with redis_manager.get_client() as client:
            location_data_str = await client.get(key)

            if not location_data_str:
                logging.info(f"No location data found in Redis for {sender}")
                return None

            location_data = json.loads(location_data_str)

            # Delete the data if requested
            if delete_after_retrieval:
                await client.delete(key)
                logging.info(
                    f"Deleted location data from Redis for {sender} after retrieval"
                )

            logging.info(
                f"Retrieved location data from Redis for {sender}: {location_data}"
            )
            return location_data

    except Exception as e:
        logging.error(
            f"Error retrieving location data from Redis: {str(e)}", exc_info=True
        )
        return None


async def clear_location_data(sender: str) -> bool:
    """
    Clear location data from Redis with error handling

    Args:
        sender: The sender's identifier (usually phone number)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        key = f"{key_name}:location_data:{sender}"
        async with redis_manager.get_client() as client:
            await client.delete(key)

        logging.info(f"Cleared location data from Redis for {sender}")
        return True

    except Exception as e:
        logging.error(
            f"Error clearing location data from Redis: {str(e)}", exc_info=True
        )
        return False


async def whether_requiring_human_confirmation(state):
    """
    Define how to determine whether an intent requires human confirmation.

    For add_project_gps intent:
    - Requires human confirmation because location data and project data may come in separate messages
    - We need to confirm if the user wants to add GPS coordinates to a project

    For location data (Latitude/Longitude):
    - If message contains coordinates, we need to confirm which project they belong to
    """
    # Always check for location data first, regardless of intent
    has_location_data = state["messages"][-1]["content"].get("Latitude") and state[
        "messages"
    ][-1]["content"].get("Longitude")

    if has_location_data:
        logging.info(
            "Message contains coordinates, confirmation needed for project association"
        )

        confirmation_required_intents = {"add_project_gps"}
        if state.get("current_intent") not in confirmation_required_intents:
            state["current_intent"] = "add_project_gps"
            state["error"] = False  # Reset any error flag
            logging.info("Setting intent to add_project_gps based on location data")

        # Check if we already have all required fields
        extracted_fields = state.get("extracted_fields", {})
        if all(
            key in extracted_fields and extracted_fields[key]
            for key in ["project_code", "location_name", "latitude", "longitude"]
        ):
            # We have all fields, no need for confirmation
            logging.info(
                "All fields for add_project_gps are present, no confirmation needed"
            )
            return False
        else:
            # Missing some fields, need confirmation
            logging.info("Missing some fields for add_project_gps, confirmation needed")
            return True

    # If no location data, check intent-based confirmation
    elif state.get("current_intent") == "add_project_gps":
        # Check if we already have all required fields
        extracted_fields = state.get("extracted_fields", {})
        if all(
            key in extracted_fields and extracted_fields[key]
            for key in ["project_code", "location_name", "latitude", "longitude"]
        ):
            # We have all fields, no need for confirmation
            logging.info(
                "All fields for add_project_gps are present, no confirmation needed"
            )
            return False
        else:
            # Missing some fields, need confirmation
            logging.info("Missing some fields for add_project_gps, confirmation needed")
            return True

    else:
        return False


async def check_gps_intent_completion(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if we have all the required fields for the add_project_gps intent
    and merge them if they come from different messages.

    This function uses the improved Redis helper functions for better reliability.
    """
    extracted_fields = state.get("extracted_fields", {})
    current_message = state["messages"][-1]["content"]
    sender = current_message.get("From")

    # Check for location data in the current message
    has_location_data = current_message.get("latitude") and current_message.get(
        "longitude"
    )

    # Check for project data in extracted fields
    has_project_data = (
        "project_code" in extracted_fields and "location_name" in extracted_fields
    )

    # Check for project data in current message
    message_body = current_message.get("Body", "").strip()
    has_project_info_in_message = (
        "project" in message_body.lower()
        or "工程" in message_body
        or "編號" in message_body
    )

    # If we have location data but no project data, store in Redis for later
    if has_location_data and not has_project_data:
        # Store location data with metadata
        metadata = {
            "message_body": message_body,
            "has_project_info": has_project_info_in_message,
            "original_body": state.get("original_body", ""),
            "timestamp": state.get("timestamp", get_this_moment().isoformat()),
        }

        await store_location_data(
            sender=sender,
            latitude=current_message.get("Latitude"),
            longitude=current_message.get("Longitude"),
            metadata=metadata,
        )

        # Update state to indicate we're waiting for project data
        state["status"] = "await_field"
        state["awaiting_project_data"] = True
        state["current_intent"] = "add_project_gps"  # Ensure intent is set

        # If message contains project info, we might need to extract it
        if has_project_info_in_message:
            state["action_result"] = "正在處理您的工程資料，請稍等..."
        else:
            state["action_result"] = (
                "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
            )

    # If we have project data but no location data, check Redis for stored location data
    elif has_project_data and not has_location_data:
        # Retrieve location data (don't delete yet)
        location_data = await retrieve_location_data(
            sender, delete_after_retrieval=False
        )

        if location_data:
            # Merge location data into extracted fields
            extracted_fields["latitude"] = location_data.get("latitude")
            extracted_fields["longitude"] = location_data.get("longitude")

            # Update state
            state["extracted_fields"] = extracted_fields
            state["status"] = "slot_filled"
            state["validated"] = True
            state["current_intent"] = "add_project_gps"  # Ensure intent is set
            state["action_result"] = "已收集所有資料，正在處理您的請求... \n\nAll data collected, processing your request..."

            # Now delete the location data since we've used it
            await clear_location_data(sender)

            logging.info(
                f"Retrieved and merged location data for {sender}: {location_data}"
            )
        else:
            # No location data found, ask user to provide it
            state["status"] = "await_field"
            state["action_result"] = (
                "您是否想要添加GPS位置資料？如是，請用WhatsApp分享您的位置。\n\nWould you like to add GPS location data to project? If yes, please share your location via WhatsApp."
            )

    elif has_location_data and has_project_info_in_message:
        state["status"] = "await_field"
        state["current_intent"] = "add_project_gps"
        state["action_result"] = "正在處理您的工程資料，請稍等... \n\nProcessing your project data, please wait..."

        # Store location data with metadata
        metadata = {
            "message_body": message_body,
            "has_project_info": True,
            "original_body": state.get("original_body", ""),
            "timestamp": state.get("timestamp", get_this_moment().isoformat()),
        }

        await store_location_data(
            sender=sender,
            latitude=current_message.get("Latitude"),
            longitude=current_message.get("Longitude"),
            metadata=metadata,
        )

    return state


async def human_confirmation_node(state):
    """
    Handle human confirmation for intents that require it, especially add_project_gps
    which needs to collect data across multiple messages
    """
    logging.info("Human confirmation node processing")
    try:
        user_message = state.get('original_body', state['messages'][-1]['content']['Body'])
        logging.info(f"User message in human confirmation: {user_message}")
        previous_intent = state.get("current_intent", "")
        sender = state["messages"][-1]["content"]["From"]

        # Get the current message content
        current_message = state["messages"][-1]["content"]
        message_body = current_message.get("Body", "").strip()

        # If this is add_project_gps intent, handle the special workflow
        if previous_intent == "add_project_gps":
            # Check if we need to complete the GPS intent with data from multiple messages
            state = await check_gps_intent_completion(state)

            # If the status is now slot_filled, we have all the data we need
            if state.get("status") == "slot_filled":
                state["human_confirmation_received"] = True
                return state

            # If we're still waiting for more data, send appropriate response
            if state.get("awaiting_project_data"):
                return state

            # Otherwise, check if this is a confirmation message
            confirmation_result = boolean_value_response(message_body)

            if "boolean_value" in confirmation_result:
                is_confirmed = confirmation_result["boolean_value"]

                if is_confirmed:
                    # User confirmed, proceed with the intent
                    state["human_confirmation_received"] = True
                    state["status"] = "slot_filled"
                    state["validated"] = True
                    state["action_result"] = "已確認，正在處理您的請求..."
                    logging.info(f"User {sender} confirmed add_project_gps action")
                else:
                    # User rejected, reset the intent
                    state["human_confirmation_received"] = False
                    state["status"] = "await_intent"
                    state["current_intent"] = ""
                    state["extracted_fields"] = {}
                    state["action_result"] = "已取消操作，請重新輸入您的請求"

                    # Clear any stored location data
                    key = f"{key_name}:location_data:{sender}"
                    async with redis_manager.get_client() as client:
                        await client.delete(key)

                    logging.info(
                        f"User {sender} rejected add_project_gps action, cleared location data"
                    )
            else:
                # Not a confirmation message, check if it contains project data
                if (
                    "project" in message_body.lower()
                    or "工程" in message_body
                    or "編號" in message_body
                ):
                    # This might be project data, try to extract it

                    try:
                        parsed_info = await add_project_gps_response(message_body)
                        logging.info(f"Extracted project info: {parsed_info}")

                        if (
                            isinstance(parsed_info, dict)
                            and parsed_info.get("project_code")
                            and parsed_info.get("location_name")
                        ):
                            # We have project data, update extracted fields
                            if "extracted_fields" not in state:
                                state["extracted_fields"] = {}

                            state["extracted_fields"]["project_code"] = parsed_info[
                                "project_code"
                            ]
                            state["extracted_fields"]["location_name"] = parsed_info[
                                "location_name"
                            ]

                            # Check if we have location data in Redis
                            key = f"{key_name}:location_data:{sender}"
                            async with redis_manager.get_client() as client:
                                location_data_str = await client.get(key)

                            if location_data_str:
                                location_data = json.loads(location_data_str)

                                # Merge location data into extracted fields
                                state["extracted_fields"]["latitude"] = (
                                    location_data.get("latitude")
                                )
                                state["extracted_fields"]["longitude"] = (
                                    location_data.get("longitude")
                                )

                                # We have all the data, proceed to execution
                                state["status"] = "slot_filled"
                                state["validated"] = True
                                state["human_confirmation_received"] = True
                                state["action_result"] = (
                                    "已收集所有資料，正在處理您的請求..."
                                )

                                # Clear Redis data
                                async with redis_manager.get_client() as client:
                                    await client.delete(key)

                                logging.info(
                                    f"Retrieved and merged location data for {sender}: {location_data}"
                                )
                            else:
                                # We have project data but no location data
                                state["status"] = "await_field"
                                state["action_result"] = (
                                    "已收到工程資料，請提供位置資料（分享您的位置）"
                                )
                        else:
                            # Could not extract project data, ask for explicit format
                            state["status"] = "await_field"
                            state["action_result"] = (
                                "請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
                            )

                    except Exception as extract_error:
                        logging.error(
                            f"Error extracting project data: {str(extract_error)}"
                        )
                        state["status"] = "await_field"
                        state["action_result"] = (
                            "請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
                        )
                else:
                    # Ask for explicit confirmation
                    state["status"] = "await_human_confirmation"
                    state["action_result"] = (
                        "您是否要為工程添加GPS位置？如是，請用WhatsApp分享您的位置。"
                    )

        # If we have coordinates in the message, handle location-based confirmation
        elif current_message.get("latitude") and current_message.get("longitude"):
            # Set intent to add_project_gps if not already set
            if not previous_intent or previous_intent != "add_project_gps":
                state["current_intent"] = "add_project_gps"

            # Check if the message body contains project information
            if (
                "project" in message_body.lower()
                or "工程" in message_body
                or "編號" in message_body
            ):
                # Try to extract project data from the message
                

                try:
                    parsed_info = await add_project_gps_response(message_body)
                    logging.info(f"Extracted project info with location: {parsed_info}")

                    if (
                        isinstance(parsed_info, dict)
                        and parsed_info.get("project_code")
                        and parsed_info.get("location_name")
                    ):
                        # We have project data and location data in the same message
                        if "extracted_fields" not in state:
                            state["extracted_fields"] = {}

                        state["extracted_fields"]["project_code"] = parsed_info[
                            "project_code"
                        ]
                        state["extracted_fields"]["location_name"] = parsed_info[
                            "location_name"
                        ]
                        state["extracted_fields"]["latitude"] = current_message.get(
                            "latitude"
                        )
                        state["extracted_fields"]["longitude"] = current_message.get(
                            "longitude"
                        )

                        # We have all the data, proceed to execution
                        state["status"] = "slot_filled"
                        state["validated"] = True
                        state["human_confirmation_received"] = True
                        state["action_result"] = "已收集所有資料，正在處理您的請求..."

                        # Clear any existing location data
                        await clear_location_data(sender)
                    else:
                        # Could not extract project data, store location and ask for explicit format
                        metadata = {
                            "message_body": message_body,
                            "has_project_info": True,
                            "original_body": state.get("original_body", ""),
                            "timestamp": state.get(
                                "timestamp", get_this_moment().isoformat()
                            ),
                        }

                        await store_location_data(
                            sender=sender,
                            latitude=current_message.get("latitude"),
                            longitude=current_message.get("longitude"),
                            metadata=metadata,
                        )

                        state["status"] = "await_field"
                        state["awaiting_project_data"] = True
                        state["action_result"] = (
                            "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
                        )
                except Exception as extract_error:
                    # Error extracting project data, store location and ask for explicit format
                    logging.error(
                        f"Error extracting project data with location: {str(extract_error)}"
                    )

                    metadata = {
                        "message_body": message_body,
                        "error": str(extract_error),
                        "original_body": state.get("original_body", ""),
                        "timestamp": state.get("timestamp", get_this_moment().isoformat()),
                    }

                    await store_location_data(
                        sender=sender,
                        latitude=current_message.get("latitude"),
                        longitude=current_message.get("longitude"),
                        metadata=metadata,
                    )

                    state["status"] = "await_field"
                    state["awaiting_project_data"] = True
                    state["action_result"] = (
                        "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
                    )
            else:
                # No project info in message, store location and ask for project information
                metadata = {
                    "message_body": message_body,
                    "has_project_info": False,
                    "original_body": state.get("original_body", ""),
                    "timestamp": state.get("timestamp", get_this_moment().isoformat()),
                }

                await store_location_data(
                    sender=sender,
                    latitude=current_message.get("latitude"),
                    longitude=current_message.get("longitude"),
                    metadata=metadata,
                )

                state["status"] = "await_field"
                state["awaiting_project_data"] = True
                state["action_result"] = "已收到位置資料，請提供工程編號和位置名稱"
                logging.info(
                    f"Stored location data and requesting project info from {sender}"
                )

        # For other confirmation scenarios
        else:
            # Use boolean_value_response to check if this is a confirmation message
            confirmation_result = boolean_value_response(message_body)

            if "boolean_value" in confirmation_result:
                is_confirmed = confirmation_result["boolean_value"]

                if is_confirmed:
                    # User confirmed, proceed with the intent
                    state["human_confirmation_received"] = True
                    state["status"] = "slot_filled"
                    state["validated"] = True
                    state["action_result"] = "已確認，正在處理您的請求..."
                    logging.info(f"User {sender} confirmed action")
                else:
                    # User rejected, reset the intent
                    state["human_confirmation_received"] = False
                    state["status"] = "await_intent"
                    state["current_intent"] = ""
                    state["extracted_fields"] = {}
                    state["action_result"] = "已取消操作，請重新輸入您的請求"
                    logging.info(f"User {sender} rejected action")
            else:
                # Not a confirmation message, ask for explicit confirmation
                state["status"] = "await_human_confirmation"
                state["action_result"] = "請確認是否繼續此操作？請回覆「是」或「否」"
                logging.info(f"Waiting for clear confirmation from user {sender}")

        # Save state to Redis for persistence
        await save_state(sender, state)
        return state

    except Exception as e:
        logging.error(f"Error in human_confirmation_node: {str(e)}", exc_info=True)
        state["error"] = True
        state["action_result"] = "處理確認時發生錯誤，請稍後再試"
        return state
