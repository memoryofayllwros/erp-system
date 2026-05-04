import logging
from datetime import date, datetime

import pytz
from pydantic import BaseModel

from src.chatbot_service.langgraph.state import WorkflowStatus_Enum
from src.chatbot_service.llm_executions.alternative_registration_replies import \
    alternative_registration_by_chatbot
from src.chatbot_service.llm_executions.leave_replies import \
    read_my_leave_records_by_chatbot
from src.chatbot_service.llm_executions.payslip_replies import \
    read_monthly_payslip_by_chatbot
from src.chatbot_service.llm_executions.project_replies import (
    add_project_by_chatbot, add_project_gps_by_chatbot,
    read_all_project_by_chatbot, read_specific_project_by_chatbot,
    remove_project_gps_location_by_chatbot)
from src.chatbot_service.llm_executions.registration_replies import \
    user_registration_by_chatbot
from src.chatbot_service.llm_executions.today_attendance_situation_replies import \
    read_today_attendance_situation_by_chatbot
from src.chatbot_service.llm_executions.unprocessed_card_replies import \
    add_unprocessed_card_by_chatbot
from src.chatbot_service.llm_executions.work_permit_replies import \
    add_worker_with_multiple_cards_by_chatbot
from src.chatbot_service.llm_executions.worker_replies import \
    read_all_worker_by_chatbot

from src.chatbot_service.llm_executions.lunch_overtime_replies import \
    add_lunch_overtime_by_chatbot
from infrastructure.redis_connection.redis_manager import save_state

from src.chatbot_service.chatbot_helpers.intent_manager import SIMPLE_READ_INTENTS

from src.utils.datetime_standarization_helpers import get_this_day
# 4. executor
async def NoSQL_execution_node(state):
    logging.info(f"Step 4: Executing functions: {state}")
    intent = state["current_intent"]
    today = get_this_day().strftime("%Y-%m-%d")
    try:
        user_messages = [m for m in reversed(state["messages"]) if m["role"] == "user"]
        sender = user_messages[0]["content"]["From"]
        media_url = user_messages[0]["content"].get("MediaUrl0", None)
    except (IndexError, KeyError, TypeError) as e:
        raise ValueError(
            f"Failed to extract sender from user message. Error: {e}, State: {state}"
        )

    fields = state.get("extracted_fields", {})
    sender = state["messages"][-1]["content"]["From"]
    logging.info(f"Sender: {sender}")

    if not fields:
        if intent not in SIMPLE_READ_INTENTS:
            raise ValueError(
                f"extracted_fields not found in state. Current state: {state}"
            )

        elif intent == "read_my_leave_records":
            response = await read_my_leave_records_by_chatbot(sender=sender)
            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

            state["action_result"] = response
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
            return state

        elif intent == "read_all_attendance_records":
            response = await read_all_project_by_chatbot(sender=sender)
            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

            state["action_result"] = response
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
            return state

        elif intent == "read_all_workers":
            response = await read_all_worker_by_chatbot(sender=sender)
            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

            state["action_result"] = response
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
            return state

        elif intent == "today_attendance_situation":
            response = await read_today_attendance_situation_by_chatbot(
                sender=sender, date_obj=today
            )
            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

            state["action_result"] = response
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
            return state

        else:
            raise ValueError(f"Unrecognized intent: {intent}")

    if intent == "add_project":
        project_title = fields.get("project_title")
        client_name = fields.get("client_name")
        region = fields.get("region")
        district = fields.get("district")
        street = fields.get("street")
        building = fields.get("building")

        response = await add_project_by_chatbot(
            project_title=project_title,
            client_name=client_name,
            region=region,
            district=district,
            street=street,
            building=building,
            sender=sender,
        )

        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "add_project_gps":
        # Log the fields for debugging
        logging.info(f"add_project_gps fields: {fields}")

        # Execute the function with the required fields
        response = await add_project_gps_by_chatbot(
            sender=sender,
            project_code=fields["project_code"],
            location_name=fields["location_name"],
            latitude=fields["latitude"],
            longitude=fields["longitude"],
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "remove_project_gps_location":
        response = await remove_project_gps_location_by_chatbot(
            sender=sender,
            project_code=fields["project_code"],
            location_name=fields["location_name"],
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "leave_application":
        from src.chatbot_service.llm_executions.leave_replies import \
            add_leave_application_by_chatbot
        response = await add_leave_application_by_chatbot(sender=sender, 
                                                             start_date=fields["start_date"], 
                                                             end_date=fields["end_date"], 
                                                             is_half_day=fields["is_half_day"],
                                                             is_upper_half_day=fields.get("is_upper_half_day", None), 
                                                             leave_type=fields["leave_type"],
                                                             project_code=fields.get("project_code", None), 
                                                             leave_reason=fields.get("leave_reason", None), 
                                                             medical_certificate=fields.get("medical_certificate", None),
                                                            )

        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "worker_upload_cards":

        # Get media URLs from state
        media_urls = state.get("media_urls", [])

        if not media_urls:
            error_message = "Missing card images. Please send your message with attached images of the cards."
            logging.error(error_message)
            state["error"] = True
            state["action_result"] = f"❌ {error_message}"

            return state

        try:
            class CardData(BaseModel):
                card_name: str
                card_image: str

            # Check if we have cards data
            cards_data = fields.get("cards_data")

            if cards_data:
                enhanced_cards_data = []
                for card in cards_data:
                    enhanced_card = card.copy()

                    enhanced_card["card_name"] = card.get("card_name")
                    enhanced_card["card_image"] = card.get(
                        "card_image"
                    )  # Keep original URL for CardData
                    enhanced_cards_data.append(enhanced_card)

                cards_data_objects = [CardData(**card) for card in enhanced_cards_data]

                result = await add_worker_with_multiple_cards_by_chatbot(
                    sender=sender, cards_data=cards_data_objects
                )

                processing_feedback = fields.get("processing_feedback", "")
                if processing_feedback:
                    # Combine database result with processing feedback
                    combined_result = (
                        f"{result}\n\n📋 **Processing Summary:**\n{processing_feedback}"
                    )
                    state["action_result"] = combined_result
                else:
                    state["action_result"] = str(result)

            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED

            await save_state(sender, state)

            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {result}")
            return state

        except Exception as e:
            error_message = f"Error processing worker registration: {str(e)}"
            logging.error(error_message, exc_info=True)
            state["error"] = True
            state["action_result"] = f"❌ {error_message}"
            return state

    elif intent == "add_unprocessed_cards":
        response = await add_unprocessed_card_by_chatbot(
            sender=sender, card_images=fields["card_images"]
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        logging.info(
            f"State for intent, add_unprocessed_cards, after add_unprocessed_cards: {state}"
        )
        return state

    elif intent == "registration":
        try:
            from src.tools.national_id_ocr_tool.national_id_ocr import \
                download_image_to_memory

            image_url = fields["card_image"]
            logging.info(f"Image URL: {image_url}")
            image_bytes = await download_image_to_memory(image_url)

            result = await user_registration_by_chatbot(
                sender=sender,
                card_name=fields["card_name"],
                english_name=fields["english_name"],
                chinese_name=fields["chinese_name"],
                national_id_no=fields["national_id_no"],
                dob=fields["dob"],
                gender=fields["gender"],
                card_image_bytes=image_bytes,
            )
            state["action_result"] = str(result)
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED

            await save_state(sender, state)

            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {result}")
            return state
        except Exception as e:
            error_message = f"Error processing user registration: {str(e)}"
            logging.error(error_message, exc_info=True)
            state["error"] = True
            state["action_result"] = f"❌ {error_message}"
        return state

    elif intent == "alternative_registration":

        image_url = fields["national_id_image"]
        logging.info(f"Image URL: {image_url}")

        try:
            response = await alternative_registration_by_chatbot(
                sender=sender,
                occupation=fields["occupation"],
                card_name=fields["card_name"],
                english_name=fields["english_name"],
                chinese_name=fields["chinese_name"],
                national_id_no=fields["national_id_no"],
                dob=fields["dob"],
                gender=fields["gender"],
                country_code=fields["country_code"],
                mobile=fields["mobile"],
                national_id_image=image_url,
            )
            logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")

            state["action_result"] = response
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        except ValueError as e:
            # Capture the specific error message about mobile number already added
            error_message = str(e)
            logging.error(f"Error in alternative registration: {error_message}")
            state["error"] = True
            state["action_result"] = (
                error_message  # Use the exact error message without adding "❌ "
            )
            state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "add_project_location_gps":
        response = await add_project_gps_by_chatbot(
            sender=sender,
            project_code=fields["project_code"],
            latitude=fields["latitude"],
            longitude=fields["longitude"],
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "read_specific_project":
        project_code = fields.get("project_code")
        if not project_code:
            raise ValueError(
                f"Missing 'project_code' for intent 'read_specific_project'. State: {state}"
            )
        response = await read_specific_project_by_chatbot(
            sender=sender, project_code=project_code
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "monthly_payslip":
        response = await read_monthly_payslip_by_chatbot(
            sender=sender, year=fields["year"], month=fields["month"]
        )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state

    elif intent == "lunch_overtime":
        response = await add_lunch_overtime_by_chatbot(sender=sender, 
                                                       lunch_ot_date=fields["lunch_ot_date"],
                                                       )
        logging.info(f"Intent: {intent}, Sender: {sender}, Response: {response}")
        state["action_result"] = response
        state["status"] = WorkflowStatus_Enum.CRUD_EXECUTED
        return state
    else:
        error_message = "sorry, I couldn't recognize what you want to do, can you speak clearly again? 🙏"
        logging.warning(f"Unrecognized intent: {intent}, State: {state}")

        state["error"] = True
        state["action_result"] = error_message
        return state
