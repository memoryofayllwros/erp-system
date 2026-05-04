import logging
import os

from src.chatbot_service.llm_prompts.alternative_registration_prompts import \
    alternative_registration_response
from src.chatbot_service.llm_prompts.payslip_prompts import \
    read_monthly_payslip_response
from src.chatbot_service.llm_prompts.project_prompts import (
    add_project_gps_response, extract_complete_project_info,
    read_specific_project_response, remove_project_gps_location_response)
from src.chatbot_service.llm_prompts.reminder_prompts import \
    add_reminder_response
from src.chatbot_service.llm_prompts.ana_prompts.leave_type_prompts import \
    add_leave_type_determination_response
from src.chatbot_service.llm_prompts.lunch_overtime_prompts import lunch_overtime_response
from src.chatbot_service.chatbot_helpers.intent_manager import VALID_INTENTS

key_name = os.getenv("KEY_NAME")

default_occupation = os.getenv("DEFAULT_OCCUPATION")
default_country_code = os.getenv("DEFAULT_COUNTRY_CODE")


async def entity_extraction_node(state):
    logging.info(f"Step 3: Extracting entities from user input. Current state: {state}")
    raw_input = state["messages"][-1]["content"]

    if isinstance(raw_input, dict):
        # Use original_body if available, otherwise use current message body
        body = state.get('original_body', raw_input['Body'])
        logging.info(f"body in step 3 is: {body}")
    else:
        body = raw_input
        raw_input = {}

    try:
        user_messages = [m for m in reversed(state["messages"]) if m["role"] == "user"]
        sender = user_messages[0]["content"]["From"]

    except (IndexError, KeyError, TypeError) as e:
        raise ValueError(
            f"Failed to extract sender from user message. Error: {e}, State: {state}"
        )

    intent = state["current_intent"]

    # Check if we have location data but no valid intent
    has_location_data = raw_input.get("Latitude") and raw_input.get("Longitude")
    if has_location_data and (not intent or intent not in {"add_project_gps"}):
        # Force the intent to add_project_gps when we have location data
        intent = "add_project_gps"
        state["current_intent"] = intent
        state["error"] = False  # Reset any error flag
        logging.info(
            f"Setting intent to add_project_gps based on location data in entity extraction"
        )

    # If we still don't have a valid intent, return early with a helpful message
    if not intent or intent not in VALID_INTENTS:
        if has_location_data:
            # If we have location data, guide the user to provide project information
            state["status"] = "await_field"
            state["current_intent"] = "add_project_gps"  # Ensure intent is set
            state["action_result"] = (
                "已收到位置資料，請提供工程編號和位置名稱，例如: 「工程編號25001，位置名稱: 中環皇后大道中123號」"
            )
            state["error"] = False  # Reset error flag
            return state
        else:
            # No valid intent and no location data
            state["error"] = True
            state["status"] = "await_intent"
            state["action_result"] = (
                "請問您需要什麼幫助？\n\nWhat can I help you with?"
            )
            return state

    fields = {}

    if intent == "add_project":
        parsed_info = extract_complete_project_info(body)
        logging.info(f"add_project parsed_info: {parsed_info}")

        if isinstance(parsed_info, dict):
            if parsed_info.get("success"):
                fields.update(parsed_info.get("data", {}))
            else:
                raise ValueError(
                    f"Failed to parse project info: {parsed_info.get('error')}"
                )
        else:
            raise ValueError(f"Failed to parse project info: {parsed_info}")

        data = parsed_info.get("data", {})
        project_title = data.get("project_title")
        client_name = data.get("client_name")
        project_location = data.get("project_location")
        region = project_location.get("region")
        district = project_location.get("district")
        street = project_location.get("street")
        building = (
            project_location.get("building")
            if project_location.get("building")
            else None
        )

        fields.update(
            {
                "project_title": project_title,
                "client_name": client_name,
                "region": region,
                "district": district,
                "street": street,
                "building": building if building else None,
            }
        )

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "monthly_payslip":
        parsed_info = read_monthly_payslip_response(body)
        logging.info(f"monthly_payslip parsed_info: {parsed_info}")
        year = parsed_info.get("year")
        month = parsed_info.get("month")

        if isinstance(parsed_info, dict):
            fields.update(parsed_info)
        else:
            raise ValueError(f"Failed to parse monthly payslip info: {parsed_info}")

        fields.update(
            {
                "year": year,
                "month": month,
            }
        )

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "alternative_registration":
        parsed_info = alternative_registration_response(body)
        logging.info(f"alternative_registration parsed_info: {parsed_info}")
        occupation = default_occupation
        country_code = default_country_code
        mobile = parsed_info.get("mobile")

        media_url = (
            state.get("media_urls", [])[0] if state.get("media_urls", []) else None
        )

        from src.tools.national_id_ocr_tool.national_id_ocr import \
            extract_national_id_info_from_media

        ocr_data = await extract_national_id_info_from_media(
            media_url
        )  # card_name, owner_name, registration_no, issue_date, expiry_date, card_image
        logging.info(f"ocr_data for image is: {ocr_data}")

        if not ocr_data:
            logging.warning(
                f"撞到啲小問題，可唔可以麻煩你試下用你張身份證？或者換張清楚啲嘅相嚟？"
            )
            state["status"] = "await_field"
            state["error"] = True
            state["action_result"] = (
                "撞到啲小問題，可唔可以麻煩你試下用你張身份證？或者換張清楚啲嘅相嚟？"
            )
            return state

        ocred_english_name = ocr_data.get("english_name")  # english_name
        ocred_chinese_name = ocr_data.get("chinese_name")  # chinese_name
        ocred_national_id_no = ocr_data.get("national_id_no")  # registration_no
        ocred_dob = ocr_data.get("dob")  # dob
        ocred_gender = ocr_data.get("gender")  # gender
        ocred_card_name = ocr_data.get("card_name")  # card_name

        # Format is already DD-MM-YYYY from OCR, we'll let the model function handle conversion

        fields.update(
            {
                "occupation": occupation,
                "mobile": mobile,
                "card_name": ocred_card_name,
                "english_name": ocred_english_name,
                "chinese_name": ocred_chinese_name,
                "national_id_no": ocred_national_id_no,
                "dob": ocred_dob,
                "gender": ocred_gender,
                "national_id_image": media_url,
            }
        )

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "check_in_via_image":
        # For image check-in, we don't need entity extraction
        # The intent can proceed directly to link generation
        logging.info(
            f"check_in_via_image intent detected - no entity extraction needed"
        )
        state["status"] = "slot_filled"
        state["extracted_fields"] = {}
        return state

    elif intent == "add_project_gps":
        if state.get("extracted_fields") and all(
            key in state["extracted_fields"]
            for key in ["project_code", "location_name", "latitude", "longitude"]
        ):
            fields = state["extracted_fields"]

            state["status"] = "slot_filled"
            return state

        # Check if we have stored project info and now have location data
        if (
            state.get("extracted_fields")
            and state["extracted_fields"].get("project_code")
            and state["extracted_fields"].get("location_name")
            and raw_input.get("Latitude")
            and raw_input.get("Longitude")
        ):

            # We have stored project info and new location data - combine them
            fields = state["extracted_fields"].copy()
            fields.update(
                {
                    "latitude": raw_input.get("Latitude"),
                    "longitude": raw_input.get("Longitude"),
                }
            )
            state["extracted_fields"] = fields
            state["status"] = "slot_filled"
            logging.info(
                f"Combined stored project info with new location data: project_code={fields.get('project_code')}, location_name={fields.get('location_name')}, lat={fields.get('latitude')}, lon={fields.get('longitude')}"
            )
            return state

        # Otherwise, try to extract from the current message
        parsed_info = await add_project_gps_response(body)
        logging.info(f"add_project_gps parsed_info: {parsed_info}")

        # Check for error response
        if isinstance(parsed_info, dict) and parsed_info.get("error"):
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = parsed_info.get("error", "無法驗證工程編號，請提供有效的工程編號")
            return state

        if isinstance(parsed_info, dict):
            # Direct dict from parser
            project_code = parsed_info.get("project_code")
            location_name = parsed_info.get("location_name")
        elif isinstance(parsed_info, str):
            # Try to parse as JSON if it's a string
            try:
                import json

                parsed_json = json.loads(parsed_info)
                project_code = parsed_json.get("project_code")
                location_name = parsed_json.get("location_name")
            except:
                raise ValueError(f"Failed to parse project info: {parsed_info}")
        else:
            raise ValueError(f"Failed to parse project info: {parsed_info}")

        logging.info(
            f"project_code is: {project_code}, location_name is: {location_name}"
        )

        # Get coordinates from raw input or from state
        latitude = raw_input.get("Latitude")
        longitude = raw_input.get("Longitude")

        # If coordinates are not in the current message, check if they're in state
        if not latitude or not longitude:
            # Check if we have coordinates in Redis
            import json

            from infrastructure.redis_connection.redis_manager import redis_manager

            try:
                sender = raw_input.get("From")
                if sender:
                    key = f"{key_name}:location_data:{sender}"
                    async with redis_manager.get_client() as client:
                        location_data_str = await client.get(key)

                    if location_data_str:
                        location_data = json.loads(location_data_str)
                        latitude = location_data.get("Latitude")
                        longitude = location_data.get("Longitude")

                        # Clear Redis data since we're using it now
                        async with redis_manager.get_client() as client:
                            await client.delete(key)

                        logging.info(
                            f"Retrieved location data from Redis: lat={latitude}, lon={longitude}"
                        )
            except Exception as e:
                logging.error(f"Error retrieving location data from Redis: {str(e)}")

        # Validate we have all required fields
        if not project_code:
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = "請提供工程編號，例如: 「工程編號25001」"
            return state

        if not location_name:
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = (
                "請提供位置名稱，例如: 「位置名稱: 中環皇后大道中123號」"
            )
            return state

        if not latitude or not longitude:
            # Store the extracted project information before asking for location data
            fields.update(
                {"project_code": project_code, "location_name": location_name}
            )
            state["extracted_fields"] = fields
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = (
                "您是否想要添加GPS位置資料？如是，請用WhatsApp分享您的位置。\n\nWould you like to add GPS location data to project? If yes, please share your location via WhatsApp."
            )
            logging.info(
                f"Stored project info (project_code: {project_code}, location_name: {location_name}) while waiting for location data"
            )
            return state

        fields.update(
            {
                "project_code": project_code,
                "location_name": location_name,
                "latitude": latitude,
                "longitude": longitude,
            }
        )
        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "registration":
        media_urls = state.get("media_urls", [])

        if not media_urls:
            state["error"] = True
            state["extracted_fields"] = fields
            state["action_result"] = (
                "可唔可以回覆我「登記」同埋你張身份證呀？🙏 真係多謝你配合呀！🙌"
            )
            return state

        media_url = media_urls[0]

        from src.tools.national_id_ocr_tool.national_id_ocr import \
            extract_national_id_info_from_media

        ocr_data = await extract_national_id_info_from_media(
            media_url
        )  # card_name, owner_name, registration_no, issue_date, expiry_date, card_image
        logging.info(f"ocr_data for image is: {ocr_data}")

        if not ocr_data:
            logging.warning(
                f"撞到啲小問題，可唔可以麻煩你試下用你張身份證？或者換張清楚啲嘅相嚟？"
            )
            state["status"] = "await_field"
            state["error"] = True
            state["action_result"] = (
                "撞到啲小問題，可唔可以麻煩你試下用你張身份證？或者換張清楚啲嘅相嚟？"
            )
            return state

        ocred_card_name = ocr_data.get("card_name")
        ocred_english_name = ocr_data.get("english_name")
        ocred_chinese_name = ocr_data.get("chinese_name")
        ocred_national_id_no = ocr_data.get("national_id_no")
        ocred_dob = ocr_data.get("dob")
        ocred_gender = ocr_data.get("gender")

        from src.utils.standardization_helpers import parse_date

        parsed_dob = await parse_date(ocred_dob)
        logging.info(f"parsed_dob is: {parsed_dob}")

        fields.update(
            {
                "card_name": ocred_card_name,
                "english_name": ocred_english_name,
                "chinese_name": ocred_chinese_name,
                "national_id_no": ocred_national_id_no,
                "dob": parsed_dob,
                "gender": ocred_gender,
                "card_image": media_url,
            }
        )

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "read_specific_project":
        parsed_info = await read_specific_project_response(body)
        logging.info(f"read_specific_project parsed_info: {parsed_info}")
        # read_specific_project parsed_info: {'success': True, 'data': {'project_code': 'WLHK25003', 'confidence': 1.0, 'method': 'fuzzy'}}

        if not parsed_info.get("success"):
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = (
                f"無法驗證工程編號。{parsed_info.get('error', '請提供有效的工程編號')}"
            )
            return state

        data = parsed_info.get("data", {})
        project_code = data.get("project_code")

        if not project_code:
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = "請提供工程編號，例如: 「WLHK25003」"
            return state

        fields.update(
            {
                "project_code": project_code,
            }
        )

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state


    elif intent == "lunch_overtime":
        parsed_info = await lunch_overtime_response(body)
        logging.info(f"lunch_overtime parsed_info: {parsed_info}")

        # Check if parsing was successful
        if parsed_info.get("status") == "error" or not parsed_info.get("date_obj"):
            error_message = parsed_info.get("message", "Sorry, I couldn't identify the lunch overtime date. Please provide a clear date.\n無法識別午餐加班日期，請提供明確日期。")
            state["error"] = True
            state["action_result"] = error_message
            state["status"] = "await_field"
            logging.warning(f"Lunch overtime parsing failed: {error_message}")
            return state

        date_obj = parsed_info.get("date_obj")

        fields.update({"lunch_ot_date": date_obj})
        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state



    elif intent == "update_project":
        parsed_info = extract_complete_project_info(body)
        logging.info(f"update_project parsed_info: {parsed_info}")

        if isinstance(parsed_info, dict):
            if parsed_info.get("success"):
                fields.update(parsed_info.get("data", {}))
            else:
                raise ValueError(
                    f"Failed to parse project update info: {parsed_info.get('error')}"
                )
        else:
            raise ValueError(f"Failed to parse project update info: {parsed_info}")

        data = parsed_info.get("data", {})
        project_title = data.get("project_title")
        client_name = data.get("client_name")
        project_location = data.get("project_location")
        region = project_location.get("region")
        district = project_location.get("district")
        street = project_location.get("street")
        building = (
            project_location.get("building")
            if project_location.get("building")
            else None
        )

        fields.update(
            {
                "project_title": project_title,
                "client_name": client_name,
                "region": region,
                "district": district,
                "street": street,
                "building": building if building else None,
            }
        )
        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "add_reminder":
        parsed_info = add_reminder_response(body)
        logging.info(f"add_reminder parsed_info: {parsed_info}")

        fields.update(parsed_info)

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "remove_project_gps_location":
        parsed_info = await remove_project_gps_location_response(body)
        logging.info(f"remove_project_gps_location parsed_info: {parsed_info}")
        
        if not parsed_info.get("success"):
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = (
                f"無法驗證工程編號。{parsed_info.get('error', '請提供有效的工程編號')}"
            )
            return state
        
        data = parsed_info.get("data", {})
        project_code = data.get("project_code")
        location_name = data.get("location_name")
        
        if not project_code or not location_name:
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = "請提供工程編號和位置名稱"
            return state

        fields.update({"project_code": project_code, "location_name": location_name})

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "add_unprocessed_cards":
        media_urls = state.get("media_urls", [])
        if not media_urls:
            state["error"] = True
            state["extracted_fields"] = fields
            state["action_result"] = "No images provided"
            return state

        card_images = []
        for media_url in media_urls:
            card_images.append(media_url)  # Simplified to just store URLs

        fields.update({"card_images": card_images})

        state["extracted_fields"] = fields
        state["status"] = "slot_filled"
        return state

    elif intent == "leave_application":
        # Process sick leave request using enhanced system
        logging.info(f"Processing leave_application intent for body: {body}")
        
        
        try:
            leave_type_result = await add_leave_type_determination_response(body)
            logging.info(f"leave_application result: {leave_type_result}")
            
            if leave_type_result.get("success"):
                # Extract fields from the result
                data = leave_type_result.get("data", {})
                
                # Map to the expected field names for leave_application
                fields.update({
                    "start_date": data.get("start_date"),
                    "end_date": data.get("end_date"),
                    "is_half_day": data.get("is_half_day"),
                    "is_upper_half_day": data.get("is_upper_half_day") if data.get("is_upper_half_day") else None,
                    "leave_type": data.get("leave_type"),
                    "project_code": data.get("project_code") if data.get("project_code") else None,
                    "leave_reason": data.get("leave_reason") if data.get("leave_reason") else None,
                    "medical_certificate": data.get("medical_certificate") if data.get("medical_certificate") else None,
                    "confidence_score": data.get("confidence_score", 0.0),
                    "confidence_reason": data.get("confidence_reason", "")
                })
                
                state["extracted_fields"] = fields
                state["status"] = "slot_filled"
                logging.info(f"Successfully extracted leave application fields: {fields}")
                return state
            else:
                # Handle extraction failure
                error_message = leave_type_result.get("error", "Unknown error in leave application processing")
                missing_fields = leave_type_result.get("missing_fields", [])
                
                if missing_fields:
                    # Ask for missing fields
                    field_messages = {
                        "start_date": "請提供請假開始日期，例如: 「今日」或「2025-01-15」",
                        "end_date": "請提供請假結束日期，例如: 「明日」或「2025-01-16」"
                    }
                    
                    missing_field_messages = [field_messages.get(field, f"請提供{field}") for field in missing_fields]
                    state["action_result"] = f"請提供以下資料: {', '.join(missing_field_messages)}"
                else:
                    state["action_result"] = f"處理請假申請時遇到問題: {error_message}"
                
                state["error"] = True
                state["status"] = "await_field"
                return state
                
        except Exception as e:
            logging.error(f"Error processing leave_application: {str(e)}")
            state["error"] = True
            state["status"] = "await_field"
            state["action_result"] = f"處理請假申請時發生錯誤: {str(e)}"
            return state

    else:
        state["error"] = True
        state["status"] = "await_field"
        state["action_result"] = (
            "AI而家仲喺開發緊，撞到啲小問題😅麻煩你搵下管理員幫手啦～我哋會慢慢學多啲嘢，希望之後可以幫到你更多～😉"
        )
        return state
