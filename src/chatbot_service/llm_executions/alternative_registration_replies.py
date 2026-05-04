import logging

from src.models.user_model import User
from src.utils.standardization_helpers import validate_mobile_from_whatsapp


async def alternative_registration_by_chatbot(
    sender,
    occupation,
    card_name,
    english_name,
    chinese_name,
    national_id_no,
    dob,
    gender,
    country_code,
    mobile,
    national_id_image,
):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)

        if not sender_info:
            raise ValueError(
                "無法解析WhatsApp號碼，請確保號碼格式正確\n\nUnable to parse the WhatsApp number — please make sure the number format is correct."
            )

        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )

        existing_user = await User.find_one(
            User.mobile == mobile, User.deleted_at == None
        )

        if existing_user:
            raise ValueError(
                f"⚠️ 呢個手機號碼為{mobile}嘅用戶已添加。\n\nThe user with this mobile number {mobile} has already been added."
            )

        function_result = await User.alternative_registration_function(
            occupation,
            card_name,
            english_name,
            chinese_name,
            national_id_no,
            dob,
            gender,
            country_code,
            mobile,
            national_id_image,
        )

        logging.info(
            f"function_result in alternative_registration_by_chatbot is: {function_result}"
        )

        result = f"Thanks, {sender_name}! {function_result.get('message')}"

        if function_result.get("status") == "success":
            return result
        else:
            raise ValueError(result)

    except Exception as e:
        logging.error(f"Error processing alternative registration: {str(e)}")
        raise
