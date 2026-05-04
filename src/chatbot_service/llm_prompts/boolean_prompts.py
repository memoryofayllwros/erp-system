import logging
import re

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.chatbot_service.chatbot_helpers.setup_llm import (gpt_4o_llm,
                                                           gpt_mini_llm)

CONFIRMATION_KEYWORDS = {
    "ok",
    "係",
    "yes",
    "得",
    "確認",
    "👌",
    "👍",
    "可以",
    "冇問題",
    "正確",
    "係啦",
    "系",
    "收到",
    "好",
    "明白",
}
REJECTION_KEYWORDS = {
    "唔係",
    "no",
    "唔得",
    "唔確認",
    "錯",
    "否",
    "唔啱",
    "唔可以",
    "cancel",
    "唔想要",
    "拒絕",
    "取消",
}


def fuzzy_match_boolean(text: str) -> bool | None:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)

    if any(kw in text for kw in CONFIRMATION_KEYWORDS):
        return True
    elif any(kw in text for kw in REJECTION_KEYWORDS):
        return False
    return None


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

class BooleanValue(BaseModel):
    boolean_value: bool


boolean_value_parser = JsonOutputParser(pydantic_object=BooleanValue)

boolean_value_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Your job is to extract a single boolean value based on the user's intent — whether they are **confirming (TRUE)** or **rejecting/negating (FALSE)** the given information.

## 💡 Judgment Criteria:
- **TRUE**: if the message contains confirmation, agreement, approval, or positive sentiment.
  - Common examples: 「ok」、「OK」、「係」、「系」、「👍」、「👌」、「冇問題」、「確認」、「得」、「yes」、「可以」、「係啦」、「正確」
- **FALSE**: if the message contains negation, disagreement, doubt, or negative sentiment.
  - Common examples: 「唔係」、「no」、「錯」、「唔得」、「唔確認」、「否」、「唔啱」、「唔可以」、「cancel」、「唔想要」

       1. **Extract and Validate**:
          - Identify the key details in the message.

        2. **Return Structured Data**:
          - Always return the data in a structured format (JSON) even if there are null values. Other functions and models will help handle the rest.
        
            ### 🚨 **STRICT OUTPUT RULES:**
            - return in JSON format:
              {{
              "boolean_value": "<true or false>", 
              }}
            
        3. ### 🧾 Example:
        For the input:「👌」
        Return:
            ```json
            {{
            "boolean_value": True
            }}
            
            """,
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=boolean_value_parser.get_format_instructions())

boolean_value_chain = boolean_value_template | gpt_4o_llm | boolean_value_parser


def boolean_value_response(body: str):
    try:
        if isinstance(body, list):
            body = " ".join(body)

        parsed = boolean_value_chain.invoke({"messages": body})
        return parsed

    except OutputParserException as e:
        logging.warning(f"LLM parsing failed: {e}. Falling back to fuzzy logic.")
    except Exception as e:
        logging.error(f"Unexpected LLM error: {e}")

    # 🧠 Step 2: Fuzzy fallback
    fallback = fuzzy_match_boolean(body)
    if fallback is not None:
        return {"boolean_value": fallback}

    return {"error": "❌ 無法判斷用戶確認意圖"}


def boolean_value_response_llm_only(body):
    try:
        if isinstance(body, list):
            body = " ".join(body)
        parse_expense_location_info = boolean_value_chain.invoke({"messages": body})

        return parse_expense_location_info

    except Exception as e:
        logging.error(f"Error determine boolean value response: {str(e)}")
        return {"error": str(e)}
