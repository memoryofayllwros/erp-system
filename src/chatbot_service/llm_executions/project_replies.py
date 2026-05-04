import logging
import os
from src.message_templates.message_response_templates import send_whatsapp_message_back
from src.chatbot_service.llm_prompts.project_prompts import (
    add_project_gps_response, add_project_response)
from src.models.project_model import Project
from src.utils.standardization_helpers import validate_mobile_from_whatsapp

base_url = os.getenv("BASE_URL")

async def read_specific_project_by_chatbot(sender, project_code):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)

        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        greeting_message = f"✅ Hi, {sender_name}!"

        project_data = await Project.read_specific_project_function(
            project_code=project_code
        )

        if not project_data.get("status") == "success":
            response_message = (
                greeting_message
                + "找不到此項目編號，可能已被刪除或尚未建立。\nThe project number could not be found. It may have been deleted or not yet created."
            )
            return response_message

        project_message = project_data.get("message")

        response_message = greeting_message + project_message

        return response_message

    except Exception as e:
        error_message = f"❌ {str(e)}"
        logging.error(f"Error in read_specific_project_by_chatbot: {error_message}")
        return error_message


async def read_all_project_by_chatbot(sender):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        # user_id = str(sender_info.id)
        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        await send_whatsapp_message_back(
            "The attendance records are being generated, this may take a little while — please wait a moment, thanks!\n出勤記錄生成緊，可能要少少時間，唔該你稍等一陣～",
            sender,
        )

        project_data = await Project.read_all_projects_function()

        greeting_message = f"✅ Hi, {sender_name}! "

        if isinstance(project_data, str):
            response_message = greeting_message + project_data
            return response_message

        if not project_data:
            response_message = (
                greeting_message
                + "There are currently no project attendance records.\n目前沒有項目出勤記錄。")
            return response_message

        project_message = (
            "\n".join(
                [(f"{idx + 1}. 📍 Project title / 項目名稱: {project.get('project_code')}: {project.get('project_title')}\n🗓️ Attendance record / 出勤記錄: {"None yet" if project.get('attendance_record_url') is None else project.get('attendance_record_url')}\n"
                  if project.get("project_location_gps")
                  else f"{idx + 1}. 📍 Project title / 項目名稱: {project.get('project_code')}: {project.get('project_title')}\n🗓️ Attendance record / 出勤記錄: {"None yet" if project.get('attendance_record_url') is None else project.get('attendance_record_url')}\n⚠️ GPS location / GPS定位: 未添加 / Not added yet.\n")
                    for idx, project in enumerate(project_data)
                ]))

        response_message = (
            greeting_message
            + f"Currently there are {len(project_data)} project attendance records.\n目前共有 {len(project_data)} 個項目出勤記錄。\n\n"
            + project_message
        )

        return response_message

    except Exception as e:
        error_message = f"❌ {str(e)}"
        logging.error(f"Error in read_all_project_by_chatbot: {error_message}")
        return error_message


async def delete_project_by_chatbot(body: str, sender: str):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)

        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )

        parsed_guest_info = await add_project_gps_response(body)
        if not isinstance(parsed_guest_info, dict):
            invalid_guests_info = str(parsed_guest_info)
            if (
                "Invalid json output:" in invalid_guests_info
                and "For troubleshooting" in invalid_guests_info
            ):
                invalid_guests_info = (
                    invalid_guests_info.split("For troubleshooting")[0]
                    .replace("Invalid json output:", "")
                    .strip()
                )
                raise ValueError(
                    f"❌ Sorry {sender_name}, 有錯誤: 無法解析輸入。\n\nError: Unable to parse the input.{invalid_guests_info}"
                )

        project_code = str(parsed_guest_info["project_code"])

        confirmation_message = await Project.delete_project_function(project_code)

        message_response = f"Thank you, {sender_name}! {confirmation_message}"

        return message_response

    except Exception as e:
        return f"{str(e)}"


async def add_project_by_chatbot(body: str, sender: str):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)

        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )

        parsed_info = add_project_response(body)
        if not isinstance(parsed_info, dict):
            invalid_info = str(parsed_info)
            if (
                "Invalid json output:" in invalid_info
                and "For troubleshooting" in invalid_info
            ):
                invalid_info = (
                    invalid_info.split("For troubleshooting")[0]
                    .replace("Invalid json output:", "")
                    .strip()
                )
                raise ValueError(
                    f"❌ Sorry {sender_name}, 有錯誤: 無法解析輸入。\n\nError: Unable to parse the input.{invalid_info}"
                )

        if not parsed_info.get("success"):
            raise ValueError(
                f"❌ Sorry {sender_name}, 有錯誤/Error: {parsed_info.get('error')}"
            )

        data = parsed_info.get("data", {})

        required_fields = [
            "region",
            "district",
            "street",
            "project_title",
        ]

        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValueError(
                f"❌ Sorry {sender_name}, 缺少必要資料:\n\nMissing necessary data:{', '.join(missing_fields)}"
            )

        result = await Project.add_project_function(
            project_title=data["project_title"],
            region=data["region"],
            district=data["district"],
            street=data["street"],
            building=data.get("building"),
            pic_name=data.get("pic_name"),
        )

        if result.get("status") == "error":
            raise ValueError(result.get("message"))

        message_response = f"Thank you, {sender_name}! {result.get('message')}"
        return message_response

    except Exception as e:
        return f"{str(e)}"


async def add_project_gps_by_chatbot(sender, 
                                     project_code, 
                                     location_name, 
                                     latitude, 
                                     longitude
):
    sender_name = None
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        if not sender_info:
            return f"Sorry, cannot find your account information. Please contact support."
        
        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        if "Manager" not in sender_info.role:
            return f"Sorry, {sender_name}, 你無權限新增打卡地點。\n\nYou don't have permission to add a check-in location."

        project_info = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )
        if not project_info:
            return f"Sorry, {sender_name}, 找不到項目編號 {project_code} 的資料。\n\nProject number {project_code} not found."

        project_id = str(project_info.id)

        result = await Project.add_project_location_gps(
            project_id, latitude, longitude, location_name
        )
        if result.get("status") == "error":
            return f"Sorry, {sender_name}, {result.get('message')}"

        message_response = f"Thank you, {sender_name}! {result.get('message')}"
        return message_response

    except Exception as e:
        return f"Sorry, {sender_name}, {str(e)}"


async def remove_project_gps_location_by_chatbot(sender, project_code, location_name):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        if not sender_info:
            return f"Sorry, cannot find your account information. Please contact support."
        
        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        if "Manager" not in sender_info.role:
            return f"Sorry, {sender_name}, you are not authorized to remove project GPS"

        result = await Project.delete_project_gps_location(project_code, location_name)
        if result.get("status") == "error":
            return f"Sorry, {sender_name}, {result.get('message')}"

        message_response = f"Thank you, {sender_name}! {result.get('message')}"
        return message_response

    except Exception as e:
        return f"Sorry, {sender_name}, {str(e)}"
