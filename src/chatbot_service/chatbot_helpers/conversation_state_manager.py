import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from infrastructure.redis_connection.redis_manager import (load_previous_state, redis_manager,
                                            save_state)

logger = logging.getLogger(__name__)

from src.utils.datetime_standarization_helpers import get_this_moment   

class ConversationStateManager:
    """
    Manages conversation state with Redis and handles message history management
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + ".ConversationStateManager")
        self.max_message_age = timedelta(hours=2)  # Keep messages for 2 hours
        self.max_messages = 50  # Maximum number of messages to keep

    async def prepare_initial_state(
        self, sender: str, form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare the initial state for a new message, handling state persistence and cleanup.
        """
        try:
            # Load previous state
            previous_state = await load_previous_state(sender)

            # Create base state for current message
            current_message = {
                "role": "user",
                "content": {
                    "Body": form_data.get("Body", ""),
                    "From": form_data.get("From", ""),
                    "MediaUrl0": form_data.get("MediaUrl0"),
                },
            }

            # Initialize new state
            current_state = {
                "messages": [current_message],
                "current_intent": "",
                "extracted_fields": {},
                "validated": False,
                "status": "await_intent",
                "action_result": "",
                "error": False,
                "media_urls": [],
                "image_collection_active": False,
                "image_collection_processed": False,
                "image_count": 0,
                "collected_image_count": 0,
                "collection_timeout_seconds": 30,
                "collection_timeout_passed": False,
                "original_body": "",
            }

            # Handle state merging and cleanup
            if previous_state:
                state = await self._merge_with_previous_state(
                    state, current_state, previous_state
                )

            self.logger.info(
                f"Prepared initial state for {sender}: {state.get('status', 'unknown')}"
            )
            return state

        except Exception as e:
            self.logger.error(f"Error preparing initial state for {sender}: {str(e)}")
            # Return minimal safe state
            return {
                "messages": [current_message],
                "current_intent": "",
                "extracted_fields": {},
                "validated": False,
                "status": "await_intent",
                "action_result": "",
                "error": False,
                "media_urls": [],
                "image_collection_active": False,
                "image_collection_processed": False,
                "image_count": 0,
                "collected_image_count": 0,
                "collection_timeout_seconds": 30,
                "collection_timeout_passed": False,
                "original_body": "",
            }

    async def _merge_with_previous_state(
        self, current_state: Dict[str, Any], previous_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Intelligently merge current message with previous state.
        """
        try:
            # Check if we should continue the previous conversation or start fresh
            should_continue = await self._should_continue_conversation(previous_state)

            if should_continue:
                self.logger.info("Continuing previous conversation")
                merged_state = self._continue_previous_conversation(
                    current_state, previous_state
                )
            else:
                self.logger.info("Starting new conversation flow")
                merged_state = self._start_new_conversation(current_state)

            return merged_state

        except Exception as e:
            self.logger.error(f"Error merging states: {str(e)}")
            return current_state

    async def _should_continue_conversation(
        self, previous_state: Dict[str, Any]
    ) -> bool:
        """
        Determine if the current message should continue the previous conversation.
        """
        try:
            # Check if previous conversation was recently active
            if not previous_state.get("messages"):
                return False

            # Check conversation timeout (30 minutes)
            last_message_time = self._get_last_message_time(previous_state)
            if (
                last_message_time
                and (get_this_moment() - last_message_time).total_seconds() > 1800
            ):
                self.logger.info("Previous conversation expired (>30 minutes)")
                return False

            # Check if previous conversation was incomplete
            previous_status = previous_state.get("status", "")
            if previous_status in ["collecting_images"]:
                logging.info(
                    f"Previous conversation incomplete (status: {previous_status})"
                )
                return True

            # Check if previous conversation had errors that might be resolved
            if previous_state.get("error") and not previous_state.get("validated"):
                logging.info("Previous conversation had errors, might be continuation")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error determining conversation continuation: {str(e)}")
            return False

    def _continue_previous_conversation(
        self, current_state: Dict[str, Any], previous_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Continue the previous conversation by merging states appropriately.
        """
        try:
            # Merge messages
            previous_messages = previous_state.get("messages", [])
            current_messages = current_state.get("messages", [])

            # Limit message history to prevent excessive accumulation
            max_messages = 10
            all_messages = previous_messages + current_messages
            if len(all_messages) > max_messages:
                # Keep recent messages and the first few for context
                recent_messages = all_messages[-max_messages:]
                all_messages = recent_messages

            # Create merged state
            merged_state = current_state.copy()
            merged_state.update(
                {
                    "messages": all_messages,
                    "current_intent": previous_state.get("current_intent", ""),
                    "extracted_fields": previous_state.get("extracted_fields", {}),
                    "validated": previous_state.get("validated", False),
                    "status": previous_state.get("status", "await_intent"),
                    "media_urls": previous_state.get("media_urls", [])
                    + current_state.get("media_urls", []),
                    "image_collection_active": previous_state.get(
                        "image_collection_active", False
                    ),
                    "image_collection_processed": previous_state.get(
                        "image_collection_processed", False
                    ),
                    "image_count": previous_state.get("image_count", 0),
                    "collected_image_count": previous_state.get(
                        "collected_image_count", 0
                    ),
                    "collection_timeout_seconds": previous_state.get(
                        "collection_timeout_seconds", 30
                    ),
                    "collection_timeout_passed": previous_state.get(
                        "collection_timeout_passed", False
                    ),
                    "original_body": previous_state.get("original_body", ""),
                }
            )

            # Handle media URL merging for current message
            current_media = current_state["messages"][-1]["content"].get("MediaUrl0")
            if current_media and current_media not in merged_state["media_urls"]:
                merged_state["media_urls"].append(current_media)

            self.logger.info(
                f"Continued conversation with intent: {merged_state['current_intent']}"
            )
            return merged_state

        except Exception as e:
            self.logger.error(f"Error continuing conversation: {str(e)}")
            return current_state

    def _start_new_conversation(self, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a new conversation, optionally preserving some context from previous state.
        """
        try:
            # Start fresh but preserve some useful context
            new_state = current_state.copy()

            # Preserve media from current message
            current_media = current_state["messages"][-1]["content"].get("MediaUrl0")
            if current_media:
                new_state["media_urls"] = [current_media]

            # Reset conversation-specific fields
            new_state.update(
                {
                    "current_intent": "",
                    "extracted_fields": {},
                    "validated": False,
                    "status": "await_intent",
                    "action_result": "",
                    "error": False,
                    "image_collection_active": False,
                    "image_collection_processed": False,
                    "image_count": 0,
                    "collected_image_count": 0,
                    "collection_timeout_seconds": 30,
                    "collection_timeout_passed": False,
                    "original_body": "",
                }
            )

            self.logger.info("Started new conversation flow")
            return new_state

        except Exception as e:
            self.logger.error(f"Error starting new conversation: {str(e)}")
            return current_state

    def _get_last_message_time(self, state: Dict[str, Any]) -> Optional[datetime]:
        """
        Extract the timestamp of the last message from state.
        """
        try:
            # This is a simplified implementation - in a real system,
            # you might want to store timestamps with messages
            messages = state.get("messages", [])
            if messages:
                # For now, assume recent messages are within reasonable time
                return get_this_moment() - timedelta(minutes=5)
            return None
        except Exception:
            return None

    async def cleanup_conversation_state(
        self, sender: str, final_state: Dict[str, Any]
    ):
        """
        Clean up conversation state after processing, preserving necessary information.
        """
        try:
            # Determine if we should preserve the state
            status = final_state.get("status", "")
            error = final_state.get("error", False)
            image_collection_active = final_state.get("image_collection_active", False)

            # Preserve state if:
            # 1. Conversation is incomplete (await_field)
            # 2. Image collection is active
            # 3. There were errors that might be resolved
            # 4. Waiting for location data for add_project_gps intent
            current_intent = final_state.get("current_intent", "")
            action_result = final_state.get("action_result", "")
            is_waiting_for_location_data = (
                current_intent == "add_project_gps"
                and status in ["await_field", "error"]
                and action_result
                and (
                    "位置資料" in action_result
                    or "位置" in action_result
                    or "location" in action_result.lower()
                )
            )

            should_preserve = (
                status == "collecting_images"
                or status == "temp_end"
                or image_collection_active == True
                or is_waiting_for_location_data  # temporal end of workflow
            )

            if should_preserve:
                # Save the state for continuation
                await save_state(sender, final_state)
                self.logger.info(
                    f"Preserved conversation state for {sender} (reason: {status})"
                )
            else:
                # Clear the state as conversation is complete
                await redis_manager.clear_state(sender)
                self.logger.info(
                    f"Cleared conversation state for {sender} (conversation complete)"
                )

        except Exception as e:
            self.logger.error(
                f"Error cleaning up conversation state for {sender}: {str(e)}"
            )

    def should_clear_extracted_fields(self, intent: str, has_new_media: bool) -> bool:
        """
        Determine if extracted_fields should be cleared for reprocessing.
        """
        try:
            # Clear extracted fields for worker_upload_cards with new images
            if intent == "add_unprocessed_cards" and has_new_media:
                self.logger.info(
                    "Clearing extracted_fields for worker_upload_cards with new media"
                )
                return True

            # Clear for other creation intents
            creation_intents = {"add_project"}
            if intent in creation_intents:
                self.logger.info(
                    f"Clearing extracted_fields for creation intent: {intent}"
                )
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error determining field clearing: {str(e)}")
            return False

    def should_clear_entire_state(
        self,
        previous_state: Dict[str, Any],
        current_intent: str,
        extracted_fields: Dict[str, Any],
    ) -> bool:
        """
        Determine if the entire state should be cleared when a new intent is classified.
        """
        try:
            # If we have a new intent with extracted fields, clear the state
            if current_intent and extracted_fields:
                previous_intent = previous_state.get("current_intent", "")

                # If this is a different intent than the previous one, clear state
                if previous_intent and previous_intent != current_intent:
                    self.logger.info(
                        f"New intent detected: {previous_intent} -> {current_intent}, clearing state"
                    )
                    return True

                # If previous state had errors and we now have a valid intent with fields, clear state
                if previous_state.get("error", False) and not previous_state.get(
                    "validated", False
                ):
                    self.logger.info(
                        f"Previous state had errors, new valid intent {current_intent} detected, clearing state"
                    )
                    return True

                # If we have extracted fields but previous state was incomplete, clear state
                if extracted_fields and previous_state.get("status") in [
                    "await_intent",
                    "collecting_images",
                ]:
                    self.logger.info(
                        f"New intent {current_intent} with extracted fields detected, clearing incomplete previous state"
                    )
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error determining state clearing: {str(e)}")
            return False

    async def handle_intent_specific_state_adjustments(
        self, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Make intent-specific adjustments to the state before processing.
        """
        try:
            intent = state.get("current_intent", "")

            # Handle worker_upload_cards specific logic
            if intent == "add_unprocessed_cards":
                # Ensure we have the media URLs from current message
                current_message = state["messages"][-1]
                current_media = current_message["content"].get("MediaUrl0")

                if current_media:
                    # Check if this is new media that should trigger reprocessing
                    if self.should_clear_extracted_fields(intent, bool(current_media)):
                        state["extracted_fields"] = {}
                        state["validated"] = False

                    # Ensure media is in media_urls
                    if current_media not in state.get("media_urls", []):
                        if "media_urls" not in state:
                            state["media_urls"] = []
                        state["media_urls"].append(current_media)

            return state

        except Exception as e:
            self.logger.error(f"Error handling intent-specific adjustments: {str(e)}")
            return state

    async def save_state(self, sender: str, state: Dict[str, Any]) -> bool:
        """
        Save conversation state for a sender

        Args:
            sender: The WhatsApp sender ID
            state: The conversation state to save

        Returns:
            True if successful, False otherwise
        """
        try:
            # Prune old messages before saving
            if "messages" in state:
                state["messages"] = self._prune_old_messages(state["messages"])

            # Save state to Redis
            return await save_state(sender, state)
        except Exception as e:
            self.logger.error(f"Error saving state for {sender}: {str(e)}")
            return False

    def _prune_old_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Prune old messages from the conversation history

        Args:
            messages: List of messages

        Returns:
            Pruned list of messages
        """
        if not messages:
            return []

        now = get_this_moment()
        pruned_messages = []

        for message in messages:
            # Skip messages without timestamp
            if not message.get("timestamp"):
                # Add timestamp if missing
                message["timestamp"] = now.isoformat()
                pruned_messages.append(message)
                continue

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(message["timestamp"])
                age = now - timestamp

                # Keep message if it's recent enough
                if age <= self.max_message_age:
                    pruned_messages.append(message)
            except (ValueError, TypeError):
                # If timestamp is invalid, update it and keep the message
                message["timestamp"] = now.isoformat()
                pruned_messages.append(message)

        # If still too many messages, keep only the most recent ones
        if len(pruned_messages) > self.max_messages:
            pruned_messages = pruned_messages[-self.max_messages :]

        return pruned_messages

    async def add_message(self, sender: str, message: Dict[str, Any]) -> bool:
        """
        Add a message to the conversation history

        Args:
            sender: The WhatsApp sender ID
            message: The message to add

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current state
            state = await load_previous_state(sender)

            # Initialize messages if not present
            if "messages" not in state:
                state["messages"] = []

            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = get_this_moment().isoformat()

            # Add message
            state["messages"].append(message)

            # Save updated state
            return await self.save_state(sender, state)
        except Exception as e:
            self.logger.error(f"Error adding message for {sender}: {str(e)}")
            return False

    async def clear_state(
        self, sender: str, state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Clear conversation state for a sender

        Args:
            sender: The WhatsApp sender ID
            state: Optional state object to process before clearing

        Returns:
            True if successful, False otherwise
        """
        try:
            # If state is provided, we can extract any necessary information
            # before clearing (e.g., for analytics or debugging)
            if state:
                self.logger.info(
                    f"Clearing state for {sender} with intent: {state.get('current_intent', 'unknown')}"
                )

                # Add any state processing logic here if needed
                # For example, you might want to log completed workflows

            return await save_state(sender, {})
        except Exception as e:
            self.logger.error(f"Error clearing state for {sender}: {str(e)}")
            return False

    async def handle_image_collection(
        self, sender: str, media_url: str, body: str, state: Dict[str, Any]
    ) -> bool:
        """
        Handle image collection for worker registration

        Args:
            sender: The WhatsApp sender ID
            media_url: The media URL
            body: The message body

        Returns:
            True if successful, False otherwise
        """
        try:
            # Add image to collection
            from infrastructure.redis_connection.redis_manager import (
                add_image_to_collection, get_image_collection)

            await add_image_to_collection(sender, media_url, body)

            # Always fetch the full collection and update state
            collection = await get_image_collection(sender)
            if collection and "images" in collection:
                state["media_urls"] = collection["images"]
                state["image_count"] = len(collection["images"])
                state["collected_image_count"] = len(collection["images"])
            else:
                state["media_urls"] = []
                state["image_count"] = 0
                state["collected_image_count"] = 0

            # Schedule processing with Temporal
            await self.schedule_image_processing(sender)

            return True
        except Exception as e:
            self.logger.error(f"Error handling image collection for {sender}: {str(e)}")
            return False

    async def schedule_image_processing(
        self, sender: str, timeout_seconds: float = 30
    ) -> bool:
        """
        Schedule image processing using Temporal

        Args:
            sender: The WhatsApp sender ID
            timeout_seconds: Timeout in seconds before collection is processed

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get Temporal client
            client = await get_temporal_client()

            # Import workflow type
            from temporal_app.workflows.image_processing_workflows import \
                ImageCollectionWorkflow

            # Start the workflow
            handle = await client.start_workflow(
                ImageCollectionWorkflow.run,
                args=[sender, timeout_seconds],
                id=f"image-collection-{sender}-{asyncio.get_event_loop().time()}",
                task_queue=TASK_QUEUE_NAME,
            )

            self.logger.info(
                f"schedule_image_processing: Scheduled Temporal workflow for image processing: {handle.id}"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to schedule Temporal workflow: {str(e)}")
            return False

    async def process_images_immediately(self, sender: str) -> bool:
        """
        Process images immediately using Temporal

        Args:
            sender: The WhatsApp sender ID

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get Temporal client
            client = await get_temporal_client()

            # Import workflow type
            from temporal_app.workflows.image_processing_workflows import \
                ImageProcessingWorkflow

            # Start the workflow
            handle = await client.start_workflow(
                ImageProcessingWorkflow.run,
                args=[sender],
                id=f"image-processing-{sender}-{asyncio.get_event_loop().time()}",
                task_queue=TASK_QUEUE_NAME,
            )

            self.logger.info(
                f"Started immediate image processing workflow: {handle.id}"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to start immediate image processing: {str(e)}")
            return False


# Global instance
conversation_state_manager = ConversationStateManager()
