import logging
from datetime import date
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class OccupationInfo(BaseModel):
    occupation: str


occupation_parser = JsonOutputParser(pydantic_object=OccupationInfo)
occupation_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a highly skilled assistant responsible for extracting and structuring an expense of project details.
            Your main goal is to ensure that all necessary information is provided and structured correctly. 

       1. **Extract and Validate**:
          - Identify the key details in the message. You will receive a message containing details such as:
                - **occupation** the occupation of the user.

        2. **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.
        
            ### 🚨 **STRICT OUTPUT RULES:**
            - return in JSON format:
              {{"occupation": "<occupation>"}}
            """,
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=occupation_parser.get_format_instructions())

occupation_chain = occupation_template | gpt_4o_llm | occupation_parser


def registration_occupation_response(body):
    try:
        if isinstance(body, list):
            body = " ".join(body)
        # Invoke the chain, which includes prompt → model → JsonOutputParser
        parsed_info = occupation_chain.invoke({"messages": body})

        return parsed_info

    except Exception as e:
        logging.error(f"Error registration occupation response: {str(e)}")
        return {"error": str(e)}
