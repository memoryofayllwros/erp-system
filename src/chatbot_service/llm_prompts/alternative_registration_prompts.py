import logging
from datetime import date
from typing import List

import pytz
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")


class AlternativeRegistrationInfo(BaseModel):
    occupation: str
    mobile: List[str]
    card_name: str = "HONG KONG PERMANENT IDENTITY CARD"


alternative_registration_parser = JsonOutputParser(
    pydantic_object=AlternativeRegistrationInfo
)
alternative_registration_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a highly skilled assistant responsible for extracting and structuring user registration details.
            Your main goal is to ensure that all necessary information is provided and structured correctly. 

       1. **Extract and Validate**:
          - Identify the key details in the message. You will receive a message containing details such as:
                - **occupation** the occupation of the user.
                - **mobile** the mobile number of the user.
                - **card_name** the type of identity card (default is "HONG KONG PERMANENT IDENTITY CARD").

        2. **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.
        
            ### 🚨 **STRICT OUTPUT RULES:**
            - return in JSON format:
              {{"occupation": "<occupation>", "mobile": "<mobile>", "card_name": "<card_name>"}}
            """,
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=alternative_registration_parser.get_format_instructions())

alternative_registration_chain = (
    alternative_registration_template | gpt_4o_llm | alternative_registration_parser
)


def alternative_registration_response(body):
    try:
        if isinstance(body, list):
            body = " ".join(body)
        # Invoke the chain, which includes prompt → model → JsonOutputParser
        parsed_info = alternative_registration_chain.invoke({"messages": body})

        return parsed_info

    except Exception as e:
        logging.error(f"Error alternative registration response: {str(e)}")
        return {"error": str(e)}
