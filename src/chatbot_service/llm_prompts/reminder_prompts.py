import json
import logging
from typing import Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import (gpt_4o_llm,
                                                           gpt_mini_llm)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

load_dotenv()


class AddReminderInfo(BaseModel):
    project_code: str
    reminder_description: str
    reminder_date: str
    reminder_time: str


add_reminder_parser = JsonOutputParser(pydantic_object=AddReminderInfo)
add_reminder_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a highly skilled assistant responsible for processing and extracting reminder details with precision. \
       Your goal is to ensure that all necessary information is provided and structured correctly. \
       Please respond in JSON format.\
    \
       You will receive a message containing details such as:\
       - **Project No** (e.g., '25001')\
       - **Reminder Description** (e.g., '油漆牆面', '清場', '其他')\
       - **Reminder Date** (e.g., '2025-06-01')\
       - **Reminder Time** (e.g., '10:00')\
        \
       1. **Extract and Validate**:\
          - Identify the key details in the message.\
          - Ensure that all four fields (project no, reminder description, reminder date, and reminder time) are present and valid.\
          - If all the data is provided, no further clarification is needed.\
          - Return the data in a structured format (JSON).\
          - The data should be in the following format:\
          {{project_code: '25001', reminder_description: '油漆牆面', reminder_date: '2025-06-01', reminder_time: '10:00'}}\
          - Project No is the project number, it is a 5 digits number.\
          - Reminder Description is the reminder description, it is a string.\
          - Reminder Date is the reminder date, it is a date in different formats, such as YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD, YYYYMMDD. Please use your intelligence to determine the correct format.\
          - Reminder Time is the reminder time, it is a time in the format of HH:MM.\
        \
        2. **Return Structured Data**:\
          - Once all necessary details are extracted and validated, return the data in a structured format (JSON).\
        \
       🛠 **Example Queries**:\
       - **User:** '添加一個提醒，項目編號是25001，提醒描述油漆牆面，2025-06-01，10:00。'\
         Return the extracted details in this format:\
         {{project_code: '25001', reminder_description: '油漆牆面', reminder_date: '2025-06-01', reminder_time: '10:00'}}\
        \
       - Please NEVER ask for clarification, just return the extracted details in the format.\
       - Please use your intelligence to get the correct information from this query. Don't hold back your intelligence.\
        ",
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=add_reminder_parser.get_format_instructions())

reminder_info_chain = add_reminder_template | gpt_4o_llm | add_reminder_parser


def add_reminder_response(body):
    try:
        if isinstance(body, list):
            body = " ".join(body)
        parse_reminder_info = reminder_info_chain.invoke({"messages": body})

        if isinstance(parse_reminder_info, dict):
            return parse_reminder_info

        if not isinstance(parse_reminder_info, dict):
            if "{" in parse_reminder_info and "}" in parse_reminder_info:
                json_start = parse_reminder_info.index("{")
                json_end = parse_reminder_info.rindex("}") + 1
                extracted_json = parse_reminder_info[json_start:json_end]
                try:
                    return json.loads(extracted_json)  # Convert to dict
                except json.JSONDecodeError as e:
                    logging.error(f"Error decoding JSON: {str(e)}")
                    return f"Error decoding JSON: {str(e)}"
        return parse_reminder_info

    except Exception as e:
        logging.error(f"Error add reminder response: {str(e)}")
        return str(e)
