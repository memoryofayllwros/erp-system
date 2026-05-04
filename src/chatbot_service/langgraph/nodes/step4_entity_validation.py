import logging

from src.chatbot_service.chatbot_helpers.extraction_templates import \
    EXTRACTION_TEMPLATES
from src.chatbot_service.chatbot_helpers.utils import is_empty
from src.chatbot_service.langgraph.state import WorkflowState, WorkflowStatus

# 3. validate functions


async def entity_validation_node(state: WorkflowState):
    logging.info(f"Step 3: Validating functions: {state}")

    try:
        user_messages = [m for m in reversed(state["messages"]) if m["role"] == "user"]
        sender = user_messages[0]["content"]["From"]

    except (IndexError, KeyError, TypeError) as e:
        raise ValueError(
            f"Failed to extract sender from user message. Error: {e}, State: {state}"
        )

    intent = state["current_intent"]
    fields = state["extracted_fields"]

    if intent == "monthly_payslip":
        state["validated"] = True
        state["status"] = "slot_filled"
        return state

    elif intent == "read_specific_project":
        state["validated"] = True
        state["status"] = "slot_filled"
        return state

    elif intent == "leave_application":
        # Enhanced validation for sick leave with confidence checking
        logging.info(f"Validating leave_application fields: {fields}")
        
        # Check confidence score
        #confidence_score = fields.get("confidence_score", 0.0)
        #if confidence_score < 0.3:
        #    state["error"] = True
        #    state["status"] = "await_field"
        #    state["action_result"] = f"請假申請資料不夠清楚，請重新提供更詳細的資料。" #信心度: {confidence_score:.2f}"
        #    return state

        # Validate required fields
        required_fields = ["start_date", "end_date", "leave_type"]
        missing_fields = []
        
        for field in required_fields:
            value = fields.get(field)
            if is_empty(value):
                missing_fields.append(field)
        
        if missing_fields:
            field_messages = {
                "start_date": "請假開始日期",
                "end_date": "請假結束日期",
                "leave_type": "請假類型"
            }
            missing_field_messages = [field_messages.get(field, field) for field in missing_fields]
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = f"請提供以下資料: {', '.join(missing_field_messages)}"
            return state
        
        # Additional validation for date format and logic
        try:
            from datetime import datetime
            start_date = datetime.strptime(fields.get("start_date"), "%Y-%m-%d")
            end_date = datetime.strptime(fields.get("end_date"), "%Y-%m-%d")
            
            if start_date > end_date:
                state["error"] = True
                state["status"] = "await_field"
                state["action_result"] = "請假開始日期不能晚於結束日期，請重新提供正確的日期\nPlease provide the correct date. The start date cannot be later than the end date."
                return state
                
        except ValueError as e:
            logging.warning(f"Date format validation failed: {e}")
            # Continue with validation even if date format is not perfect
        
        state["validated"] = True
        state["status"] = "slot_filled"
        logging.info(f"Leave application validation successful: {fields}")
        return state

    elif intent == "lunch_overtime":
        state["validated"] = True
        state["status"] = "slot_filled"
        logging.info(f"Lunch overtime validation successful: {fields}")
        return state

    elif intent == "registration":
        missing_fields = []

        if is_empty(fields.get("card_name")):
            missing_fields.append("card_name")
        if is_empty(fields.get("english_name")):
            missing_fields.append("english_name")
        if is_empty(fields.get("chinese_name")):
            missing_fields.append("chinese_name")
        if is_empty(fields.get("national_id_no")):
            missing_fields.append("national_id_no")
        if is_empty(fields.get("dob")):
            missing_fields.append("dob")
        if is_empty(fields.get("gender")):
            missing_fields.append("gender")
        if is_empty(fields.get("card_image")):
            missing_fields.append("card_image")

        if missing_fields:
            logging.info(f"missing_fields in entity_validation_node: {missing_fields}")
            polite_message = (
                f"你嘅身份證資料唔齊全，請提供完整嘅身份證資料。{missing_fields}"
            )
            state["status"] = "await_field"
            state["error"] = True
            state["action_result"] = polite_message
            return state
        else:
            process_fields = {
                "card_name": fields.get("card_name"),
                "english_name": fields.get("english_name"),
                "chinese_name": fields.get("chinese_name"),
                "national_id_no": fields.get("national_id_no"),
                "dob": fields.get("dob"),
                "gender": fields.get("gender"),
                "card_image": fields.get("card_image"),
            }

            # Note: field_validation_function is not defined - you may need to implement this
            # validation_response = await field_validation_function(process_fields)

            # if validation_response.get("status") == "error":
            #     # Handle error case here
            #     pass

            state["validated_fields"] = process_fields
            # state["action_result"] = validation_response

        state["validated"] = True
        state["status"] = "slot_filled"
        return state

    else:
        template = EXTRACTION_TEMPLATES.get(intent)
        if template is None:
            error_message = f"Validation template not found for intent: {intent}"
            logging.error(error_message)
            state["action_result"] = (
                "Sorry, I encountered an error processing your request."
            )
            state["error"] = True
            return state

        required_fields = template.get("required_fields", [])

        missing_fields = []
        for field in required_fields:
            value = fields.get(field)

            if field == "materials":
                if not isinstance(value, list) or len(value) == 0:
                    missing_fields.append(field)
                else:
                    for i, item in enumerate(value):
                        if is_empty(item.get("material_name")):
                            missing_fields.append(f"materials[{i}].material_name")
                        if is_empty(item.get("material_qty")):
                            missing_fields.append(f"materials[{i}].material_qty")
                        if is_empty(item.get("material_unit")):
                            missing_fields.append(f"materials[{i}].material_unit")
                        if is_empty(item.get("unit_price")):
                            missing_fields.append(f"materials[{i}].unit_price")

            elif field == "quotation_items":
                if not isinstance(value, list) or len(value) == 0:
                    missing_fields.append(field)
                else:
                    for i, item in enumerate(value):
                        if is_empty(item.get("material_no")):
                            missing_fields.append(f"quotation_items[{i}].material_no")
                        if is_empty(item.get("material_qty")):
                            missing_fields.append(f"quotation_items[{i}].material_qty")

            elif field == "cards_data":
                if not isinstance(value, list) or len(value) == 0:
                    missing_fields.append(field)
                else:
                    for i, item in enumerate(value):
                        if is_empty(item.get("card_type")):
                            missing_fields.append(f"cards_data[{i}].card_type")
                        if is_empty(item.get("card_no")):
                            missing_fields.append(f"cards_data[{i}].card_no")
                        if is_empty(item.get("card_issue_date")):
                            missing_fields.append(f"cards_data[{i}].card_issue_date")
                        card_type = item.get("card_type", "")
                        if is_empty(item.get("card_expiry_date")):
                            if (
                                "registration" in card_type.lower()
                                or "註冊" in card_type
                            ):
                                missing_fields.append(
                                    f"cards_data[{i}].card_expiry_date"
                                )
                        if is_empty(item.get("card_image")):
                            missing_fields.append(f"cards_data[{i}].card_image")

            elif field == "card_images":
                if not isinstance(value, list) or len(value) == 0:
                    missing_fields.append(field)
                else:
                    for i, item in enumerate(value):
                        # card_images contains URL strings, not dictionaries
                        if is_empty(item):
                            missing_fields.append(f"card_images[{i}]")

            elif is_empty(value):
                missing_fields.append(field)

        if missing_fields:
            logging.info(f"missing_fields in entity_validation_node: {missing_fields}")
            polite_message = "AI而家仲學緊嘢，你可唔可以試下用你張身份證？或者換張清楚啲嘅相嚟？ \n\n如果仲搞唔掂，就麻煩你搵管理員幫幫手啦～唔好意思要你行多幾步 🙏 我哋會慢慢進步，希望之後可以幫到你更多～😉"

            state["status"] = "await_field"
            state["error"] = True
            state["action_result"] = polite_message
            return state

        state["validated"] = True
        state["status"] = "slot_filled"
        return state
