import logging

from src.chatbot_service.llm_prompts.classification_prompts.classification import \
    classify_intent
from infrastructure.redis_connection.redis_manager import clear_image_collection, clear_state
from src.chatbot_service.chatbot_helpers.intent_manager import VALID_INTENTS

async def intent_classifier_node(state):
    logging.info("Step 1: Classifying user intent")
    try:
        user_message = state.get('original_body', state['messages'][-1]['content']['Body'])
        logging.info(f"User message in step 1: {user_message}")
        previous_intent = state.get("current_intent", "")

        sender = state["messages"][-1]["content"]["From"]
        intent = await classify_intent(user_message, sender)


        has_location_data = state["messages"][-1]["content"].get("Latitude") and state[
            "messages"
        ][-1]["content"].get("Longitude")

        if has_location_data:
            logging.info("Location data detected, setting intent to add_project_gps")
            state["current_intent"] = "add_project_gps"
            state["error"] = False
        elif intent is None:
            # None indicates an error in classification or unknown intent
            logging.warning("Intent classification returned None")
            state["current_intent"] = ""
            state["error"] = True
            state["action_result"] = "Sorry, I couldn't identify your intent. Please provide more information.\n無法識別您的意圖，請提供更多信息。"
        elif isinstance(intent, str) and intent.startswith("Error:"):
            # Error message from classify_intent
            logging.error(f"Intent classification error: {intent}")
            state["current_intent"] = ""
            state["error"] = True
            state["action_result"] = "Sorry, an error occurred while processing your request. Please try again later.\n處理您的請求時發生錯誤，請稍後再試。"
        elif not isinstance(intent, str):
            # Unexpected return type
            logging.error(f"Unexpected intent type: {type(intent)}")
            state["current_intent"] = ""
            state["error"] = True
            state["action_result"] = "Sorry, an error occurred while processing your request. Please try again later.\n系統錯誤，請稍後再試。"
        elif intent not in VALID_INTENTS:
            # Invalid intent string
            logging.warning(
                f"Invalid intent detected: {intent}, setting to empty string"
            )
            state["current_intent"] = ""
            state["error"] = True
            state["action_result"] = "Sorry, I couldn't identify your intent. Please provide more information.\n無法識別您的意圖，請提供更多信息。"
        else:
            # Valid intent
            state["current_intent"] = intent
            state["error"] = False

        if state["current_intent"] == "":
            state["status"] = "await_document_validation"
            return state

        # If this is a new intent different from the previous one, clear the state
        if previous_intent and previous_intent != intent:
            logging.info(
                f"New intent detected: {previous_intent} -> {intent}, clearing state"
            )
            try:
                sender = state["messages"][-1]["content"]["From"]
                await clear_state(sender)
                await clear_image_collection(sender)
                logging.info(
                    f"State and image collection cleared for {sender} due to new intent"
                )

                # Reset the state to start fresh
                state["extracted_fields"] = {}
                state["validated"] = False
                state["error"] = False
                state["action_result"] = ""
                state["media_urls"] = []
                state["image_collection_active"] = False
                state["image_collection_processed"] = False
                state["image_count"] = 0
                state["collected_image_count"] = 0
                state["original_body"] = state.get("original_body", "")
            except Exception as clear_error:
                logging.error(
                    f"Error clearing state for new intent: {str(clear_error)}"
                )

        # Special handling for add_unprocessed_cards intent with media
        if (
            intent == "add_unprocessed_cards"
            and state.get("media_urls")
            and len(state.get("media_urls", [])) > 0
        ):
            logging.info(
                f"add_unprocessed_cards intent with {len(state.get('media_urls', []))} images, setting status to await_intent"
            )
            state["status"] = "await_intent"
            state["image_collection_active"] = True
            state["image_collection_processed"] = False
        else:
            state["status"] = "await_document_validation"

        return state

    except Exception as e:
        logging.error(f"Intent classifier error: {str(e)}")
        state["error"] = True
        state["status"] = "await_document_validation"
        return state
