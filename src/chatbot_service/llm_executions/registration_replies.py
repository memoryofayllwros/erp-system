import base64
import logging

from src.models.user_model import NationalIDInfo, User
from src.utils.standardization_helpers import normalize_mobile_from_whatsapp


async def user_registration_by_chatbot(
    sender,
    card_name,
    english_name,
    chinese_name,
    national_id_no,
    dob,
    gender,
    card_image_bytes,
):

    try:
        # Normalize mobile number
        mobile_info = normalize_mobile_from_whatsapp(sender)
        if not mobile_info:
            raise ValueError(
                "無法解析WhatsApp號碼，請確保號碼格式正確\n\nUnable to parse the WhatsApp number — please make sure the number format is correct."
            )

        country_code = mobile_info.get("country_code")
        mobile_digits = mobile_info.get("mobile_digits")

        if not country_code or not mobile_digits:
            raise ValueError(
                "無法獲取國家代碼或手機號碼，請確保號碼包含國家代碼\n\nUnable to get country code or mobile number — please ensure the number includes the country code."
            )

        logging.info(
            f"Processing registration for mobile: {country_code}{mobile_digits}"
        )

        # Check for existing user
        existing_user = await User.find_one(
            User.country_code == country_code,
            User.mobile == mobile_digits,
            User.deleted_at == None,
        )

        if existing_user:
            logging.info(f"Found existing user: {existing_user}")
            return "⚠️ 此用戶已經註冊。\n\nThis user has already been registered."

        # Create NationalIDInfo object if card_name is identity card
        national_id_document = None
        if (
            "identity" in card_name.lower()
            or "permanent" in card_name.lower()
            or "身份證/Identity card" in card_name
        ):
            # Convert bytes to base64 string for proper storage
            if isinstance(card_image_bytes, bytes):
                card_image_b64 = base64.b64encode(card_image_bytes).decode("utf-8")
            else:
                # If it's already a string (e.g., base64 or URL), use as is
                card_image_b64 = card_image_bytes

            national_id_document = {"card_image_front": card_image_b64}

        # Use a simple default password
        default_password = f"{mobile_digits}"  # Just use the mobile number
        logging.info(f"default_password in registration_replies is: {default_password}")

        # Create new user with both English and Chinese names
        new_user_info = await User.add_user_by_chatbot_function(
            country_code=country_code,
            mobile=mobile_digits,
            english_name=english_name,
            chinese_name=chinese_name,
            gender=gender,
            dob=dob,
            national_id_no=national_id_no,
            address="",  # Provide empty string as default
            password=default_password,
            occupation="worker",  # Default occupation
            national_id_card=national_id_document,
        )

        if new_user_info.get("status") == "success":
            message = new_user_info.get("message")
            learning_video_message = """
\n\n請睇埋以下影片，畀我你嘅瀏覽器定位權限，咁你就可以順利使用打卡功能。
https://drive.google.com/drive/folders/1A9nIPLba8boguyKQC2Mc6odbuaV62Pug
            
感謝你配合！\n\nThank you for your cooperation!
            """
            message += learning_video_message
            return message
        else:
            raise ValueError(new_user_info.get("message"))

    except Exception as e:
        logging.error(f"Error processing user registration: {str(e)}")
        raise
