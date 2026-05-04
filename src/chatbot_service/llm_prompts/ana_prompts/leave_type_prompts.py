
"""
first step is to determine the leave type:
1. sick leave
2. annual leave
3. other leave


sample input:
"請今日病假"
"請明日半天病假"
"請11號-15號年假"
"請今日年假"
"請今日半日病假"
"請今日上午半日病假"
"請後日下午病假"
"請前日病假"

"""
from typing import Optional
from pydantic import BaseModel
from src.models.application_and_approval_model import LeaveType
import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from typing import List, Dict, Tuple
import difflib
from datetime import timedelta
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm
from src.utils.datetime_standarization_helpers import get_this_day

leave_type_list = [
    {"leave_type_id": LeaveType.SICK_LEAVE, "leave_type_name": "sick leave"},
    {"leave_type_id": LeaveType.COMPENSATORY_LEAVE, "leave_type_name": "compensatory leave"},
    {"leave_type_id": LeaveType.ANNUAL_LEAVE, "leave_type_name": "annual leave"},
    {"leave_type_id": LeaveType.OTHER_LEAVE, "leave_type_name": "other leave"},
]

class LeaveTypeDeterminationInfo(BaseModel):
    start_date: str
    end_date: str
    is_half_day: bool
    is_upper_half_day: Optional[bool] = None # True for upper half day, False for lower half day
    leave_type: LeaveType
    leave_reason: Optional[str] = None
    matched_leave_type: str
    project_code: Optional[str] = None
    confidence_score: float = 0.0 # 0.0 to 1.0
    confidence_reason: str



leave_type_determination_parser = JsonOutputParser(pydantic_model=LeaveTypeDeterminationInfo)

leave_type_determination_template = ChatPromptTemplate.from_messages([
    ("system", """
        You are a helpful assistant that determines the leave type and temporal information from text.
        
        **Current Date Information:**
        - Today's date: {current_date}
        - Tomorrow's date: {tomorrow_date}
        - Yesterday's date: {yesterday_date}
        - Day after tomorrow's date: {day_after_tomorrow_date}
        
        **Your Task:**
        Determine the leave type and temporal information from the given text.
        
        **Available Leave Types:**
        - 'sick leave' (病假) - for illness, medical conditions
        - 'compensatory leave' (補假) - for compensatory leave
        - 'annual leave' (年假) - for vacation, personal time off
        - 'other leave' (其他假期) - for any other type of leave
        
        **Temporal Information to Extract:**
        - start_date: The start date of the leave in YYYY-MM-DD format
        - end_date: The end date of the leave in YYYY-MM-DD format
        - is_half_day: Whether the leave is for half a day (true/false)
        - is_upper_half_day: If is_half_day is true, whether it's for the morning (true) or afternoon (false)
        
        **IMPORTANT - Date Format Rules:**
        - When you see dates in DD/MM/YYYY format (e.g., "03/11/2025"), interpret them as Day/Month/Year
        - "03/11/2025" means November 3, 2025 (not March 11, 2025)
        - Always convert dates to YYYY-MM-DD format in your output
        - For Chinese date expressions like "11號" or "11月3日", interpret as Month/Day in the current year context
        
        **Examples (using current date context):**
        - Input: "請今日病假" → Output: {{
            "leave_type": "sick leave",
            "start_date": "{current_date}",
            "end_date": "{current_date}",
            "is_half_day": false,
            "is_upper_half_day": null
          }}
        - Input: "請明日半天病假" → Output: {{
            "leave_type": "sick leave",
            "start_date": "{tomorrow_date}",
            "end_date": "{tomorrow_date}",
            "is_half_day": true,
            "is_upper_half_day": null
          }}
        - Input: "請11號-15號年假" → Output: {{
            "leave_type": "annual leave",
            "start_date": "2025-11-11",
            "end_date": "2025-11-15",
            "is_half_day": false,
            "is_upper_half_day": null
          }}
        - Input: "請03/11/2025病假" → Output: {{
            "leave_type": "sick leave",
            "start_date": "2025-11-03",
            "end_date": "2025-11-03",
            "is_half_day": false,
            "is_upper_half_day": null
          }}
          (Remember: "03/11/2025" = Day/Month/Year = November 3, 2025, NOT March 11, 2025)
        - Input: "請今日上午半日病假" → Output: {{
            "leave_type": "sick leave",
            "start_date": "{current_date}",
            "end_date": "{current_date}",
            "is_half_day": true,
            "is_upper_half_day": true
          }}
        - Input: "請後日下午病假" → Output: {{
            "leave_type": "sick leave",
            "start_date": "{day_after_tomorrow_date}",
            "end_date": "{day_after_tomorrow_date}",
            "is_half_day": true,
            "is_upper_half_day": false
          }}
        
        **Output Format:**
        Always return JSON with this exact structure:
        {{
          "leave_type": "<leave_type>",
          "start_date": "YYYY-MM-DD",
          "end_date": "YYYY-MM-DD",
          "is_half_day": <true/false>,
          "is_upper_half_day": <true/false/null>
        }}
        
        Use today's date ({current_date}) as reference for relative dates like "今日" (today), "明日" (tomorrow), "後日" (day after tomorrow), etc.
        """
        ),
        ("human", "{message}"),
    ]
).partial(format_instructions=leave_type_determination_parser.get_format_instructions())

# LLM-based leave type determination prompt
llm_leave_type_determination_template = ChatPromptTemplate.from_messages([
    ("system", """
        You are an expert leave type determination assistant. Your task is to determine the leave type from the given text.
        
        **Available Leave Types:**
        {leave_types}
        
        **Matching Criteria:**
        1. Consider semantic similarity and industry equivalence
        2. Handle both English and Chinese leave types
        3. Account for abbreviations and full names (e.g., 'AC' = 'Air Conditioning')
        4. Consider regional variations in naming conventions
        5. If no good match exists (confidence < 0.5), respond with "None"
        
        **Examples:**
        - "I want to take a sick leave from 2025-01-01 to 2025-01-02" → Output: {{"leave_type": "sick", "start_date": "2025-01-01", "end_date": "2025-01-02"}}
        - "I want to take a annual leave from 2025-01-01 to 2025-01-02" → Output: {{"leave_type": "annual", "start_date": "2025-01-01", "end_date": "2025-01-02"}}
        - "compensatory leave 2025-01-01 to 2025-01-02" → Output: {{"leave_type": "compensatory", "start_date": "2025-01-01", "end_date": "2025-01-02"}}
        - "comp leave 2025-01-02" → Output: {{"leave_type": "compensatory", "start_date": "2025-01-02", "end_date": "2025-01-02"}}

        Respond with JSON containing the best match and confidence score.
        """),
    ("human", """Match this leave type name to the available list:
    
Leave type to match: "{message}"

Provide your response in JSON format with:
- matched_leave_type: the best matching leave type from the list (or "None" if no match)
- confidence: a score from 0 to 1 indicating how confident you are
- reasoning: brief explanation of the match
    """),
]).partial(format_instructions=leave_type_determination_parser.get_format_instructions())

# Update the templates with available leave type names
leave_type_determination_prompt = leave_type_determination_template.partial(
    leave_type_list="\n".join([f"{item['leave_type_id']}: {item['leave_type_name']}" for item in leave_type_list])
)


leave_type_determination_chain = leave_type_determination_prompt | gpt_4o_llm | leave_type_determination_parser

def find_closest_leave_type_match_fuzzy(extracted_leave_type: str, leave_types: List[Dict]) -> Tuple[Optional[str], Optional[str], float]:
    """
    Find the closest matching leave type using fuzzy string matching.
    Returns a tuple of (leave_type, leave_type_name, confidence_score).
    """
    if not extracted_leave_type or extracted_leave_type.lower() == "null" or extracted_leave_type is None:
        return None, None, 0.0
    
    matches = difflib.get_close_matches(extracted_leave_type.lower(), 
                                      [leave_type["leave_type_name"].lower() for leave_type in leave_types], 
                                      n=1, 
                                      cutoff=0.4)
    
    if matches:
        best_match = matches[0]
        for leave_type in leave_types:
            if leave_type["leave_type_name"].lower() == best_match:
                # Calculate similarity ratio as confidence
                similarity = difflib.SequenceMatcher(None, extracted_leave_type.lower(), best_match).ratio()
                return leave_type["leave_type_id"], leave_type["leave_type_name"], similarity
    
    return None, None, 0.0

async def find_closest_leave_type_match_llm(extracted_leave_type: str, leave_types: List[Dict]) -> Tuple[Optional[str], Optional[str], float]:
    """
    Find the closest matching leave type using LLM semantic matching.
    Returns a tuple of (leave_type_id, leave_type_name, confidence_score).
    """
    if not extracted_leave_type or extracted_leave_type.lower() == "null" or extracted_leave_type is None:
        return None, None, 0.0
    
    try:
        # For exact matches, we can skip the LLM call
        for leave_type in leave_types:
            if leave_type["leave_type_name"].lower() == extracted_leave_type.lower():
                return leave_type["leave_type_id"], leave_type["leave_type_name"], 1.0
        
        # If no exact match, use the LLM for semantic matching
        # Create a string with all available leave types for the LLM
        leave_types_str = "\n".join([f"- {lt['leave_type_name']}" for lt in leave_types])
        
        # Create a prompt for the LLM
        prompt = f"""Match this leave type: '{extracted_leave_type}' to one of the following leave types:
        {leave_types_str}
        
        Return the best match and a confidence score between 0 and 1."""
        
        # Invoke LLM to find the best match
        match_result = await leave_type_determination_chain.ainvoke({"message": prompt})
        
        logging.info(f"LLM match result: {match_result}")
        
        # Extract the matched leave type name and confidence
        matched_leave_type = match_result.get("leave_type")
        confidence = 0.9  # Default high confidence for LLM matches
        
        if not matched_leave_type or matched_leave_type == "None":
            return None, None, 0.0
        
        # Find the leave_type_id from leave_types
        for leave_type in leave_types:
            if leave_type["leave_type_name"].lower() == matched_leave_type.lower():
                return leave_type["leave_type_id"], leave_type["leave_type_name"], confidence
        
        return None, None, 0.5  # Lower confidence if no exact match in leave_types
    
    except Exception as e:
        logging.error(f"Error in LLM leave type determination: {str(e)}")
        return None, None, 0.0

async def find_closest_leave_type_match_hybrid(extracted_leave_type: str, leave_types: List[Dict]) -> Tuple[Optional[str], Optional[str], float]:
    """
    Use hybrid approach: try LLM first, fall back to fuzzy matching if LLM confidence is low.
    Returns a tuple of (leave_type_id, leave_type_name, confidence_score, method_used).
    """
    if not extracted_leave_type or extracted_leave_type.lower() == "null" or extracted_leave_type is None:
        return None, None, 0.0, "none"
    
    # Try LLM matching first
    llm_leave_type_id, llm_leave_type_name, llm_confidence = await find_closest_leave_type_match_llm(
        extracted_leave_type, 
        leave_types
    )
    
    # If LLM confidence is high enough, use that result
    if llm_confidence >= 0.7:
        logging.info(f"Using LLM match with confidence {llm_confidence}")
        return llm_leave_type_id, llm_leave_type_name, llm_confidence
    
    # Fall back to fuzzy matching
    fuzzy_leave_type_id, fuzzy_leave_type_name, fuzzy_confidence = find_closest_leave_type_match_fuzzy(
        extracted_leave_type, 
        leave_types
    )
    
    if fuzzy_confidence > llm_confidence:
        logging.info(f"Using fuzzy match with confidence {fuzzy_confidence} (LLM had {llm_confidence})")
        return fuzzy_leave_type_id, fuzzy_leave_type_name, fuzzy_confidence
    
    # Return best result
    if llm_leave_type_id:
        logging.info(f"Using LLM match with confidence {llm_confidence}")
        return llm_leave_type_id, llm_leave_type_name, llm_confidence
    
    logging.info(f"Using fuzzy match with confidence {fuzzy_confidence}")
    return fuzzy_leave_type_id, fuzzy_leave_type_name, fuzzy_confidence

async def add_leave_type_determination_response(body: str, use_llm_match: bool = True) -> dict:
    """
    Extract leave type and temporal information (start_date, end_date, is_half_day, is_upper_half_day) using LLM.
    
    Args:
        body: Input text containing leave type and temporal information
        use_llm_match: If True, use LLM-based matching; if False, use fuzzy matching only
    """
    try:
        # Use the predefined leave types for testing
        leave_types = leave_type_list
        leave_type_names = [leave_type["leave_type_name"] for leave_type in leave_types]
        
        if isinstance(body, list):
            body = " ".join(body)

        # Get current date and calculate related dates for the prompt
        current_date = get_this_day()
        tomorrow_date = current_date + timedelta(days=1)
        yesterday_date = current_date - timedelta(days=1)
        day_after_tomorrow_date = current_date + timedelta(days=2)
        
        # Use the enhanced chain for both leave type and temporal information determination
        parse_result = leave_type_determination_chain.invoke({
            "message": body,
            "current_date": current_date.strftime("%Y-%m-%d"),
            "tomorrow_date": tomorrow_date.strftime("%Y-%m-%d"),
            "yesterday_date": yesterday_date.strftime("%Y-%m-%d"),
            "day_after_tomorrow_date": day_after_tomorrow_date.strftime("%Y-%m-%d")
        })
        logging.info(f"LLM parse result: {parse_result}")
        
        # Extract leave type information
        leave_type_name = parse_result.get("leave_type")
        
        # Extract temporal information
        start_date = parse_result.get("start_date")
        end_date = parse_result.get("end_date")
        is_half_day = parse_result.get("is_half_day", False)
        is_upper_half_day = parse_result.get("is_upper_half_day")

        # Enhanced validation and confidence scoring
        confidence_score = 0.0
        confidence_reason = ""
        
        # Match the extracted leave type name with the best one in leave_types
        if leave_type_name:
            if use_llm_match:
                # Use hybrid approach (LLM with fuzzy fallback)
                leave_type_id, matched_leave_type_name, confidence = await find_closest_leave_type_match_hybrid(
                    leave_type_name, 
                    leave_types
                )
                logging.info(f"Leave type match - ID: {leave_type_id}, Name: {matched_leave_type_name}, Confidence: {confidence}")
            else:
                # Use fuzzy matching only
                leave_type_id, matched_leave_type_name, confidence = find_closest_leave_type_match_fuzzy(
                    leave_type_name, 
                    leave_types
                )
                logging.info(f"Fuzzy match - ID: {leave_type_id}, Name: {matched_leave_type_name}, Confidence: {confidence}")
            
            # Create the result dictionary with all information
            result = {
                "leave_type_id": leave_type_id,
                "leave_type": matched_leave_type_name if matched_leave_type_name else leave_type_name,
                "start_date": start_date,
                "end_date": end_date,
                "is_half_day": is_half_day,
                "is_upper_half_day": is_upper_half_day
            }
            
            # Calculate overall confidence score
            temporal_confidence = 0.9 if start_date and end_date else 0.5
            confidence_score = (confidence + temporal_confidence) / 2
            confidence_reason = f"Leave type match confidence: {confidence:.2f}, Temporal extraction confidence: {temporal_confidence:.2f}"
        else:
            result = {
                "leave_type_id": None,
                "leave_type_name": None,
                "leave_type": None,  # Add leave_type field which is needed by downstream processes
                "start_date": start_date,
                "end_date": end_date,
                "is_half_day": is_half_day,
                "is_upper_half_day": is_upper_half_day
            }
            confidence_score = 0.5
            confidence_reason = "No leave type detected"

        return {
            "success": True,
            "data": result,
            "confidence_score": confidence_score,
            "confidence_reason": confidence_reason
        }
    
    except Exception as e:
        logging.error(f"Error in add_leave_type_determination_response: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }