
import logging
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class ReadMonthlyPayslipInfo(BaseModel):
    year: Optional[str] = None
    month: Optional[str] = None


read_monthly_payslip_parser = JsonOutputParser(pydantic_object=ReadMonthlyPayslipInfo)
read_monthly_payslip_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a highly skilled assistant responsible for extracting and structuring information for a payslip.
            Your main goal is to ensure that the necessary information is provided and structured correctly. 

       You will receive a message containing details such as:
       - **year (REQUIRED)** the year of the payslip
       - **month (REQUIRED)** the month of the payslip

       If the year or month is not provided, return null for that field.

       1. **Extract and Validate**:
          - Identify the key details in the message.
          - Ensure that this specific field (year and month) is present and valid.
          - Extract `year` and `month` if provided.

        2. **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.
          - If the year or month is not provided, return null for that field.
          - If both year and month are provided, return year and month only.

            ### 🚨 **STRICT OUTPUT RULES:**
            - return in JSON format:
              {{"year": "<year>",
                "month": "<month>"}}
            """,
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=read_monthly_payslip_parser.get_format_instructions())

read_monthly_payslip_chain = (
    read_monthly_payslip_template | gpt_4o_llm | read_monthly_payslip_parser
)


def read_monthly_payslip_response(body):
    try:
        if isinstance(body, list):
            body = " ".join(body)
        parsed_info = read_monthly_payslip_chain.invoke({"messages": body})

        return parsed_info

    except Exception as e:
        logging.error(f"Error find payslip response: {str(e)}")
        return {"error": str(e)}
