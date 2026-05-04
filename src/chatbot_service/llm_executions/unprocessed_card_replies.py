import logging

from src.models.user_model import User
from src.utils.standardization_helpers import validate_mobile_from_whatsapp


async def add_unprocessed_card_by_chatbot(sender: str, card_images: list):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        sender_name = sender_info.chinese_name
        mobile = sender_info.mobile

        response = await User.add_unprocessed_card_function(
            mobile=mobile, card_images=card_images
        )
        message = response.get("message")
        result = f"Hi, {sender_name}! {message}"
        return result

    except Exception as e:
        logging.error(f"Failed to add unprocessed card. Error: {e}")
        raise ValueError(f"Failed to add unprocessed card. Error: {e}")
