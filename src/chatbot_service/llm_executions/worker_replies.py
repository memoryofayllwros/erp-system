import os
import logging
from datetime import datetime

from src.models.user_model import User
from src.utils.standardization_helpers import validate_mobile_from_whatsapp
from src.pdf_templates.worker_info_xlsx import create_worker_info_excel
from src.models.client_company_model import ClientCompany
from src.utils.datetime_standarization_helpers import get_this_moment

base_url = os.getenv("BASE_URL")

async def read_all_worker_by_chatbot(sender: str):
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        
        if not sender_info:
            return "❌ Unable to identify sender. Please register first."

        sender_name = sender_info.english_name if sender_info.english_name else sender_info.chinese_name if sender_info.chinese_name else sender_info.payee_name
        greeting_message = f"Hi, {sender_name}!\n"

        # Get all workers
        all_workers_info = await User.read_all_workers_by_director_function()
        
        # Handle error case
        if isinstance(all_workers_info, str):
            return greeting_message + all_workers_info
        
        if not all_workers_info:
            return greeting_message + "✅ 目前沒有工人/No workers data in the system。"
        
        # Process worker data
        workers_data = []
        for worker in all_workers_info:
            # Get mobile numbers - handle both list and string formats
            mobile_list = worker.get("mobile") or []
            if isinstance(mobile_list, str):
                mobile_list = [mobile_list]
            
            phone_1 = mobile_list[0] if len(mobile_list) > 0 else ""
            phone_2 = mobile_list[1] if len(mobile_list) > 1 else ""

            # Get work type - convert enum to string if needed
            work_type = worker.get("work_type")
            if hasattr(work_type, 'value'):
                work_type = work_type.value
            elif work_type is not None:
                work_type = str(work_type)
            else:
                work_type = ""

            worker_data = {
                "work_type": work_type,
                "staff_no": worker.get("staff_no") or "",
                "payee_name": worker.get("payee_name") or "",
                "chinese_name": worker.get("chinese_name") or "",
                "english_name": worker.get("english_name") or "",
                "occupation": worker.get("occupation") or "",
                "1st_phone": phone_1,
                "2nd_phone": phone_2,
            }
            workers_data.append(worker_data)
        
        # Generate filename with timestamp
        timestamp = get_this_moment().strftime("%Y%m%d_%H%M%S")
        filename = f"worker_list_{timestamp}.xlsx"
        
        # Create Excel file and upload to GridFS
        worker_list_id = await create_worker_info_excel(workers_data, filename)
        
        if worker_list_id:
            # Save worker_list_id in client company model
            await ClientCompany.update_worker_list_id(sender_info.client_company_id, worker_list_id)
            
            response_message = (
                greeting_message + f"✅ 目前共有 {len(workers_data)} 位工人。\n"
                + f"Currently there are {len(workers_data)} workers.\n"
                + f"{base_url}/all-workers-info-xlsx/{worker_list_id}\n"
            )
        else:
            response_message = (
                greeting_message + "❌ 生成工人列表時發生錯誤。\n"
                + "Error generating worker list.\n"
            )
        
        return response_message

    except Exception as e:
        logging.error(f"Error in read_all_worker_by_chatbot: {str(e)}")
        return f"❌ {str(e)}"
