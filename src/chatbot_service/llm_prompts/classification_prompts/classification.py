import logging
from dotenv import load_dotenv
from src.utils.standardization_helpers import validate_mobile_from_whatsapp
from src.chatbot_service.llm_prompts.classification_prompts.worker_classification_prompts import classify_worker_intent
from src.chatbot_service.llm_prompts.classification_prompts.admin_classification_prompts import classify_admin_intent
from src.chatbot_service.llm_prompts.classification_prompts.manager_classification_prompts import classify_manager_intent
from src.chatbot_service.llm_prompts.classification_prompts.fallback_prompts import falldown_smalltalk_response

load_dotenv()


def sanitize_text(text):
    """Sanitize text to handle Unicode characters properly"""
    if isinstance(text, bytes):
        return text.decode("utf-8")
    return str(text)


def classify_by_role(sender_info, message: str) -> str:
    # Handle case where sender_info might be None or role might be None
    if not sender_info or not hasattr(sender_info, "role") or not sender_info.role:
        logging.warning(f"Missing or invalid sender_info or role: {sender_info}")
        return None

    try:
        # Convert role list to lowercase strings for case-insensitive matching
        roles = [str(r).lower() for r in sender_info.role]

        # Check if any role contains the target string
        if any("manager" in role for role in roles):
            return classify_manager_intent(message)
        elif any("worker" in role for role in roles):
            return classify_worker_intent(message)
        elif any("admin" in role for role in roles):
            return classify_admin_intent(message)
        else:
            logging.warning(f"Invalid or inactive sender role: {sender_info.role}")
            return None
    except Exception as e:
        logging.error(f"Error in classify_by_role: {str(e)}")
        return None


async def classify_intent(body: str, sender: str):
    try:
        sanitized_body = sanitize_text(body)
        sender_info = await validate_mobile_from_whatsapp(sender)

        if sender_info is None:
            intent = falldown_smalltalk_response(sanitized_body)
            logging.info(f"Intent: {intent}, classify_unknown_people_intent")
            return intent

        intent = classify_by_role(sender_info, sanitized_body)
        logging.info(f"Intent: {intent}, classify_by_role")
        return intent

    except Exception as e:
        logging.error(f"Intent classification error: {str(e)}")
        return f"Error: {str(e)}"
