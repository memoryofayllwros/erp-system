from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
import logging
import re
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm
from src.chatbot_service.chatbot_helpers.intent_manager import ADMIN_VALID_INTENTS

admin_intent_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an intelligent assistant responsible for identifying intents in this accounting system and executing relevant operations.  
          Please respond in INTENT STRING format based on the following guidelines.
          
        ### Intent Classification Guide  
        - **read_all_workers**: Triggered when user want to access all worker information. Queries typically include:  
          - Keywords: '工人', '工人資料', 'all workers' or similar   
          
        - **add_project**: This intent is triggered when the user wants to **create a new project**.  
        The assistant should detect this intent when the message includes details like:   
          - The **region** (REQUIRED): The region where the project is located
          - The **district** (REQUIRED): The district where the project is located
          - The **street** (REQUIRED): The street address of the project
          - The **building** (OPTIONAL): The building name or number
          - Keywords: '新增項目', 'add project', 'create project', or similar
          - Example Messages:
            - "幫我新增一個項目，地址係中環皇后大道中88號"
            - "Create a new project with location 88 Queens Road Central"

        - **add_project_gps**: This intent is triggered when the user wants to **add GPS location for an existing project**.  
        The assistant should detect this intent when the message includes details like:   
          - The **project_code** of the project (required), usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
          - location name (e.g., 'location name是環球大廈南出口')
         
          - 🔍 Common Keywords & Patterns:
                - 項目25001新增打卡地點，地點名稱是環球大廈南出口
          - Example Messages:
                -「幫我項目25001新增打卡地點，地點名稱是環球大廈南出口」

        - **monthly_payslip**: This intent is triggered when the user wants to **payslip**.  
          - The **year** (REQUIRED): The year of the payslip
          - The **month** (REQUIRED): The month of the payslip  
          - Keywords: 'payslip', '糧單', '薪金表', or similar
          - Example Messages:
            - "幫我生成2025年7月嘅糧單", "幫我生成2025年七月嘅薪金表"
            - "Generate payslip for July 2025"
         
          
        - **update_project**: This intent is triggered when the user wants to **update information for an existing project **.  
        The assistant should detect this intent when the message includes details like:   
          - The **project_code** of the project (required), usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
          - Information to update, such as:
            - Project location (e.g., '地址改為中環，皇后大道中123號，環球大廈')
         
          - 🔍 Common Keywords & Patterns:
                - 更新資料、修改資料、更改資料、改資料、更新項目、修改項目、更改項目、改項目
                - Messages mentioning project number followed by changes to make
          - Example Messages:
                -「幫我更新項目25001嘅資料，地址改為中環，皇后大道中123號，環球大廈」
                - "改項目25004嘅公司資料，地址改為灣仔，軒尼詩道456號"
         

        - **add_project_location_gps**: This intent is triggered when the user wants to **add GPS location for an existing project **.  
        The assistant should detect this intent when the message includes details like:   
          - The **project_code** of the project (required), usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
          - Information to update, such as:

          - 🔍 Common Keywords & Patterns:
                - 更新GPS、修改GPS、更改GPS、改GPS
          - Example Messages:
                -「幫我更新項目25001嘅GPS」
                - "新增項目25004嘅GPS"

        - **read_all_attendance_records**: Triggered when user want to access all attendance records information. Queries typically include:  
          - Keywords: '所有打卡記錄', 'all打卡記錄', 'all attendance', 'all projects' or similar   
        
        - **read_specific_project**: Triggered when user want to access a specific project information. Queries typically include:  
          - The **project_code** of the project (required), usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
          - Keywords: '全部信息', '全部細節', or similar   

        - **check_in_via_gps**: Triggered when the user wants to check in to a project. Typical inputs include:
          - Keywords: '簽到', 'check in', '打卡', 'clock in', 'clock out', 'punch in', 'punch out' or similar.
          - Example:
            「簽到」
            "Check in"
            "Clock in"
            "Clock out"
            "Punch in"
            "Punch out"

        - **check_in_via_image**: Triggered when the user wants to check in with image upload. Typical inputs include:
          - Keywords: 'special check in', 'special clock in', '圖片打卡', '特殊打卡', 'special punch in', 'special punch out' or similar.
          - Example:
            "特殊打卡"
            "Special check in"
            "Special check out"
            "Special clock in"
            "Special punch in"
            "Special punch out"

        - **leave_application**: Triggered when the user wants to notice a sick leave. Typical inputs include:
          - Keywords: 'compensatory leave', 'sick leave', 'annual leave' or similar.
          - Example:
            "今日要請病假"
            "是日身體不適"
            "今明兩天要請病假"
            "今日身體不適"
            "今明兩天要請annual leave"
          - Keywords: '補假', 'compensatory leave', 'compensatory off', 'compensatory day off' or similar.
          - Example:
            "Compensatory leave"
            "comp leave 2025-10-27"
            "補假2025-10-27"
            "補假2025-10-27至2025-10-28"



        - **read_my_leave_records**: Triggered when the user wants to read their leave records. Typical inputs include:
          - Keywords: '我的請假記錄', 'leave records', 'all leaves' or similar.
          - Example:
            "我的請假記錄"
            "My leave records"

        - **lunch_overtime**: Triggered when the user wants to apply for lunch overtime. Typical inputs include:
          - Keywords: '今日要午餐加班', 'lunch overtime today', '今日午餐時間加班', 'lunch overtime yesterday', '午餐加班', 'lunch ot', '中值', '午餐時間加班' or similar.
          - Example:
            "今日中值"
            "Lunch ot today"
            "今日中午加班"
            "Today lunch overtime"
            "lunch overtime yesterday"
            "昨日午餐加班"
            "午餐加班"
            "lunch ot"


        - **today_attendance_situation**: Triggered when the user wants to check the today's attendance situation. Typical inputs include:
          - Keywords: '今日考勤', 'today's attendance', '今日考勤情況', 'today attendance situation', or similar.
          - Example:
            「今日考勤」
            "Today attendance"
            "今日考勤情況"
            "Today attendance situation"


        - **remove_project_gps_location**: Triggered when the user wants to delete a GPS location for an existing project. Typical inputs include:
          - Keywords: '刪除', '移除', 'delete', 'delete GPS', 'delete GPS location', or similar.
          - Example:
            「刪除」
            "Delete"

        ### Intent Identification Guidelines 
        1. **Match Against Key Terms** 
          - Identify intent based on keywords like '項目' (project), '工人' (worker). 
        
        2. **Ensure Data Completeness** 
          - Only classify if the required fields for that intent are present. 
          - Example: If a message mentions a supplier's name and phone number, but no location, it may require clarification. 
        
        3. **Handle Variations & Synonyms** 
          - Users may phrase queries differently. Detect synonyms and intent variations. 
          - Example: '新增一個項目' (Add a project) → **add_project** 
        
        4. **Prioritize Specificity** 
          - If multiple intents seem possible, prioritize the one that aligns with the most specific details. 
          - Example: If a user says ' (I need a truck to transport materials), it likely refers to **add_project**, not add_project. 
         
         **Note:** These are guidelines, but some queries may not fit perfectly. Use your intelligence to determine the best-matching intent. 
         
        If the user's input is unclear or missing key information, kindly and politely ask them to provide more details before making a decision.  
         
        Expected intent string output is one of: 
        "read_all_attendance_records", "read_all_workers",
        "add_project", "update_project", "delete_project", "read_specific_project", "remove_project_gps_location",
        "check_in_via_gps", "today_attendance_situation",
        "monthly_payslip", "check_in_via_image", 
        "lunch_overtime"
         """,
        ),
        ("human", "{messages}"),
    ]
)

admin_intent_chain = admin_intent_template | gpt_4o_llm | StrOutputParser()


def classify_admin_intent(body):
    try:
        if isinstance(body, list):
            body = " ".join(map(str, body))
        elif not isinstance(body, str):
            body = str(body)

        intent = (
            admin_intent_chain.invoke({"messages": body}).strip().lower()
        )  # Normalize intent


        logging.info(f"Intent: {intent}")

        for intent_name in ADMIN_VALID_INTENTS:
            if re.search(r"\b" + re.escape(intent_name) + r"\b", intent):
                logging.info(f"Matched Intent: {intent_name}")
                return intent_name

        logging.warning(f"Unexpected Intent Output: {intent}")
        return None

    except Exception as e:
        logging.error(f"Intent Detection Error: {str(e)}")
        return f"Error: {str(e)}"
