import json
import logging

import pytz
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")


class AddWorkerProjectInfo(BaseModel):
    project_code: str


worker_project_info_parser = JsonOutputParser(pydantic_object=AddWorkerProjectInfo)

worker_project_info_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        You are a helpful assistant that extracts information from the text.
        You will be given text. Extract the following if present:
        - Project No: please provide the project number, usually consists of four letters and five-digit number, for example, 'WLHK25003', 'WCGEO25002', etc.
     
        **Extract and Validate**:
          - Identify the key details in the message.
          - Ensure that this field (project_code) is present and valid.

        **Example Queries**:
          Return the extracted details in this format:
          {{project_code: 'WLHK25003'}}

        **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.
     
            ### 🚨 **STRICT OUTPUT RULES:**
            - returnin JSON format:
              {{
              "project_code": "<project code>"
              }}
            """,
        ),
        ("human", "{message}"),
    ]
).partial(format_instructions=worker_project_info_parser.get_format_instructions())

worker_project_info_chain = (
    worker_project_info_template | gpt_4o_llm | worker_project_info_parser
)


async def worker_project_info_response(body: str) -> dict:
    try:
        if isinstance(body, list):
            body = " ".join(body)

        parse_worker_project_info = worker_project_info_chain.invoke({"message": body})
        logging.info(f"parse_worker_project_info is: {parse_worker_project_info}")
        return {"success": True, "data": parse_worker_project_info}

    except Exception as e:
        logging.error(f"Error in worker_project_info_response: {str(e)}")
        return {"success": False, "error": str(e)}


class AddCardNameInfo(BaseModel):
    card_name: str


card_name_info_parser = JsonOutputParser(pydantic_object=AddCardNameInfo)

card_name_info_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        You are a helpful assistant that extracts information from the text.
        You will be given text. Extract the following if present:
        - Card Name: please identify the type of card mentioned in the text.
     
        **Extract and Validate**:
          - Identify if the card is a construction worker registration card or a safety training certificate.
          - Map the card to one of the two standardized values: 'Construction Workers Registration Card' or 'Construction Industry Safety Training Certificate'

        **Mapping Rules**:
          - If the card mentions "registration", "worker card", "註冊證" → use 'registration_card'
          - If the card mentions "safety", "training", "certificate", "安全訓練", "証明書", "certified worker" → use 'safety_training_certificate'

        **Example Input/Output**:
          Input: "建造業工人註冊證 Worker Registration Card No. CWR12345678" -> registration_card

          Input: "強制性安全訓練證明書 Safety Training Certificate" -> safety_training_certificate
     
          Input: "Certificate of Certified Worker" -> safety_training_certificate

        ### 🚨 **STRICT OUTPUT RULES:**
        - You must return EXACTLY one of these two values:
          - registration_card
          - safety_training_certificate

        # Return your answer in JSON format like this:
          {{
            'card_name': <'registration_card'>
          }}
          OR
          {{
            'card_name': <'safety_training_certificate'>
          }}
        """,
        ),
        ("human", "{message}"),
    ]
).partial(format_instructions=card_name_info_parser.get_format_instructions())

card_name_info_chain = card_name_info_template | gpt_4o_llm | card_name_info_parser


async def format_card_name_info_response(ocr_card_type: str) -> dict:
    try:
        parse_card_name_info = card_name_info_chain.invoke({"message": ocr_card_type})
        return parse_card_name_info

    except Exception as e:
        logging.error(f"Error in format_card_name_info_response: {str(e)}")
        return {"success": False, "error": str(e)}


class AddWorkerNameInfo(BaseModel):
    worker_name: str


worker_name_info_parser = JsonOutputParser(pydantic_object=AddWorkerNameInfo)

worker_name_info_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        You are a helpful assistant that extracts information from the text.
        You will be given text, may be combination of Chinese and English, such as '駱超強 Lok Chiu Keurg', 'Hau Man Kit 侯文傑'. Extract the following if present:
        - Worker Name: please extract the worker's Chinese name, something like "駱超強", "侯文傑", overlook the English name.
     
        **Extract and Validate**:
          - Identify the key details in the message.
          - Ensure that all one field (worker_name) is present and valid.

        **Example Queries**:
          Return the extracted details in this format:
          {{worker_name: '侯文傑'}}

        **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.

            ### 🚨 **STRICT OUTPUT RULES:**
            - returnin JSON format:
              {{
              "worker_name": "<Chinese name>"
              }}
            """,
        ),
        ("human", "{message}"),
    ]
).partial(format_instructions=worker_name_info_parser.get_format_instructions())

worker_name_info_chain = (
    worker_name_info_template | gpt_4o_llm | worker_name_info_parser
)


async def format_worker_name_info_response(body: str) -> dict:
    try:
        parse_worker_name_info = worker_name_info_chain.invoke({"message": body})
        return parse_worker_name_info
    except Exception as e:
        logging.error(f"Error in format_worker_name_info_response: {str(e)}")
        return {"success": False, "error": str(e)}
