import logging
import re
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from src.chatbot_service.chatbot_helpers.intent_manager import WORKER_VALID_INTENTS
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm


worker_intent_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an intelligent assistant responsible for identifying intents in this accounting system and executing relevant operations.  
          Please respond in INTENT STRING format based on the following guidelines.
          
        ### Intent Classification Guide  
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



        - **add_medical_certificate_for_sick_leave**: Triggered when the user wants to add a medical certificate for a sick leave. Typical inputs include:
          - Keywords: '醫生証明', 'medical certificate', '病假証明', 'sick leave certificate' or similar.
          - Example:
            "醫生紙"
            "Medical certificate"
            "病假証明"
            "Sick leave certificate"


        - **read_my_leave_records**: Triggered when the user wants to read their leave records. Typical inputs include:
          - Keywords: '我的請假記錄', 'leave records', 'all leaves' or similar.
          - Example:
            "我的請假記錄"
            "My leave records"


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


        ### Intent Identification Guidelines 
        1. **Match Against Key Terms** 
          - Identify intent based on keywords like '簽到' (check in).
          - The user should only use one of the two intents, if both intents are not correct, return None.
        
        2. **Ensure Data Completeness** 
          - Only classify if the required fields for that intent are present. 
          - Example: If a message mentions a project number, but no location, it may require clarification. 
  
        3. **Handle Variations & Synonyms** 
          - Users may phrase queries differently. Detect synonyms and intent variations. 
          - Example: '簽到' (Check in、Clock in、Punch in) → **check_in_via_gps** 
          - Example: '特殊打卡' (Special check in、Special clock in、Special punch in) → **check_in_via_image**
        
        4. **Prioritize Specificity** 
          - If multiple intents seem possible, prioritize the one that aligns with the most specific details. 
          - Example: If a user says '打卡' (Clock in、Punch in), it likely refers to **check_in_via_gps**, not check_in_via_image. 
          - Example: If a user says '特殊打卡' (Special check in、Special clock in、Special punch in), it likely refers to **check_in_via_image**, not check_in_via_gps. 
         
         **Note:** These are guidelines, but some queries may not fit perfectly. Use your intelligence to determine the best-matching intent. 
         
        If the user's input is unclear or missing key information, kindly and politely ask them to provide more details before making a decision.  
         
        Expected intent string output is one of: 
        "check_in_via_gps", 
        "check_in_via_image",
        "leave_application",
        "add_medical_certificate_for_sick_leave",
        "read_my_leave_records",
        "lunch_overtime",
         """,
        ),
        ("human", "{messages}"),
    ]
)

worker_intent_chain = worker_intent_template | gpt_4o_llm | StrOutputParser()


def classify_worker_intent(body):
    try:
        if isinstance(body, list):
            body = " ".join(map(str, body))
        elif not isinstance(body, str):
            body = str(body)

        intent = (
            worker_intent_chain.invoke({"messages": body}).strip().lower()
        )  # Normalize intent

        logging.info(f"Intent: {intent}")

        for intent_name in WORKER_VALID_INTENTS:
            if re.search(r"\b" + re.escape(intent_name) + r"\b", intent):
                logging.info(f"Matched Intent: {intent_name}")
                return intent_name

        logging.warning(f"Unexpected Intent Output: {intent}")
        # Always return None for unrecognized intent
        return None

    except Exception as e:
        logging.error(f"Intent Detection Error: {str(e)}")
        return f"Error: {str(e)}"

