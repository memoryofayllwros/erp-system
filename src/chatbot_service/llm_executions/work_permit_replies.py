import logging
from datetime import date

from src.models.project_model import Project
from src.models.user_model import User
from src.pdf_templates.work_permit_pdf.merge_work_permit import \
    generate_work_permit_pdf
from infrastructure.database.database_connection import get_grid_fs
from src.utils.standardization_helpers import validate_mobile_from_whatsapp


async def add_worker_by_chatbot(
    sender: str,
    project_code: str,
    card_type: str,
    card_holder_name: str,
    card_no: str,
    card_issue_date: date,
    card_expiry_date: date,
    card_image: str,
):
    try:

        sender_info = await validate_mobile_from_whatsapp(sender)
        logging.info(f"sender_info is: {sender_info}")

        current_project = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )

        if not current_project:
            raise ValueError(f"No project found with project_code {project_code}")

        added_worker_info = await User.add_user_card_function(
            card_type=card_type,
            project_code=project_code,
            card_holder_name=card_holder_name,
            card_no=card_no,
            card_issue_date=card_issue_date,
            card_expiry_date=card_expiry_date,
            card_image=card_image,
        )

        if not added_worker_info:
            raise ValueError("Failed to add worker")

        work_permit_content = await generate_work_permit_pdf(project_code)

        work_permit_filename = f"work_permit_{project_code}.pdf"

        grid_fs = await get_grid_fs()
        work_permit_id_object = await grid_fs.upload_from_stream(
            filename=work_permit_filename, source=work_permit_content
        )

        logging.info(
            f"Uploaded work permit PDF to GridFS with ID {str(work_permit_id_object)}"
        )

        # Update project with work permit ID
        current_project.work_permit_id = str(work_permit_id_object)
        await current_project.save()

        return f"✅ 工人/Worker {card_holder_name} 已成功登記到項目/Successfully registered to project {project_code}。\n\n📋 工作證已更新/Work permit updated。"

    except Exception as e:
        logging.error(f"Error in add_worker_by_chatbot: {str(e)}")
        raise


async def add_worker_with_multiple_cards_by_chatbot(
    sender: str, project_code: str, cards_data: list
):
    """
    Add a worker with multiple cards from different images
    """
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        logging.info(f"sender_info is: {sender_info}")

        current_project = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )

        if not current_project:
            raise ValueError(f"No project found with project_code {project_code}")

        processed_cards_data = []
        for card_data in cards_data:
            if hasattr(card_data, "dict"):
                card_dict = card_data.dict()
            else:
                card_dict = card_data

            processed_card = {
                "sender": sender,
                "project_code": project_code,
                "card_type": card_dict.get("card_type", ""),
                "card_holder_name": card_dict.get(
                    "card_holder_name", ""
                ),  # Add worker name to each card
                "card_no": card_dict.get("card_no", ""),
                "card_issue_date": card_dict.get("card_issue_date"),
                "card_expiry_date": card_dict.get("card_expiry_date"),
                "card_image": card_dict.get("card_image", ""),
            }
            processed_cards_data.append(processed_card)

        for card in processed_cards_data:
            added_worker_info = await add_worker_by_chatbot(
                sender=card.get("sender"),
                project_code=card.get("project_code"),
                card_type=card.get("card_type"),
                card_holder_name=card.get("card_holder_name"),
                card_no=card.get("card_no"),
                card_issue_date=card.get("card_issue_date"),
                card_expiry_date=card.get("card_expiry_date"),
                card_image=card.get("card_image"),
            )
            if not added_worker_info:
                raise ValueError("Failed to add worker")

        return f"✅ 已成功登記到項目/Successfully registered to project {project_code}。\n\n📋 理已處/Handled {len(processed_cards_data)} 張證件/work permits。"

    except Exception as e:
        logging.error(f"Error in add_worker_with_multiple_cards_by_chatbot: {str(e)}")
        raise
