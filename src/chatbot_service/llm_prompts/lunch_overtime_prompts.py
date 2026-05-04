
"""
Lunch overtime processing with temporal word extraction.
Handles temporal words like "today", "tomorrow", "yesterday" and converts them to proper date format.

Sample inputs:
- "lunch overtime today"
- "lunch overtime tomorrow" 
- "lunch overtime yesterday"
- "lunch overtime 15號"
"""
from typing import Optional, Any
from pydantic import BaseModel
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from typing import List, Dict, Tuple
import difflib
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm
from src.utils.datetime_standarization_helpers import get_this_day
from src.nlp_helpers.process_temporal_words import process_temporal_entities
from datetime import date, timedelta

class LunchOvertimeInfo(BaseModel):
    date_obj: date
    confidence: float = 0.0
    reasoning: str = ""


lunch_overtime_parser = JsonOutputParser(pydantic_model=LunchOvertimeInfo)

# Function to process lunch overtime with temporal extraction
def process_lunch_overtime_temporal(message: str) -> LunchOvertimeInfo:
    """
    Process lunch overtime request with temporal word extraction.
    Uses the existing temporal processing infrastructure to handle temporal words.
    """
    try:
        # Use the existing temporal processing function
        temporal_info = process_temporal_entities(message)
        
        # Extract date from temporal processing
        if temporal_info.start_date:
            from datetime import datetime
            date_obj = datetime.strptime(temporal_info.start_date, "%Y-%m-%d").date()
            confidence = temporal_info.confidence
            reasoning = f"Extracted from temporal entities: {[e.original_text for e in temporal_info.entities_found]}"
        else:
            # Fallback to today if no temporal info found
            date_obj = get_this_day()
            confidence = 0.5
            reasoning = "No temporal entities found, defaulting to today"
        
        return LunchOvertimeInfo(
            date_obj=date_obj,
            confidence=confidence,
            reasoning=reasoning
        )
        
    except Exception as e:
        logging.error(f"Error processing lunch overtime temporal: {e}")
        # Fallback to today
        return LunchOvertimeInfo(
            date_obj=get_this_day(),
            confidence=0.3,
            reasoning=f"Error in temporal processing: {str(e)}"
        )

# LLM-based lunch overtime determination prompt (for complex cases)
llm_lunch_overtime_template = ChatPromptTemplate.from_messages([
    ("system", """
        You are an expert lunch overtime determination assistant. Your task is to determine the lunch overtime date from the given text.
        
        **Current Date:** {current_date}
        
        **Examples:**
        - "lunch overtime today" → Output: {{"date_obj": "{current_date}", "confidence": 1.0, "reasoning": "Direct reference to today"}}
        - "lunch overtime tomorrow" → Output: {{"date_obj": "{tomorrow_date}", "confidence": 1.0, "reasoning": "Direct reference to tomorrow"}}
        - "lunch overtime 15號" → Output: {{"date_obj": "{current_month_15}", "confidence": 0.9, "reasoning": "Chinese date format"}}
        - "lunch overtime 2025-10-24" → Output: {{"date_obj": "2025-10-24", "confidence": 1.0, "reasoning": "Explicit date format"}}
        
        **Instructions:**
        1. Extract the date from the message
        2. Convert temporal words (today, tomorrow, yesterday) to actual dates
        3. Handle Chinese date formats (15號, 1月15日, etc.)
        4. Handle explicit date formats (YYYY-MM-DD)
        5. Provide confidence score (0-1) and reasoning
        
        Respond with JSON containing the date object, confidence, and reasoning.
        """),
    ("human", "Message: {message}"),
]).partial(format_instructions=lunch_overtime_parser.get_format_instructions())




async def lunch_overtime_response(message: str) -> Dict[str, Any]:

    try:
        logging.info(f"Processing lunch overtime request: {message}")
        
        # First try temporal processing (faster and more reliable for common cases)
        temporal_result = process_lunch_overtime_temporal(message)
        
        # If confidence is high enough, use temporal result
        if temporal_result.confidence >= 0.8:
            logging.info(f"Using temporal processing result: {temporal_result}")
            return {
                "status": "success",
                "date_obj": temporal_result.date_obj,
                "confidence": temporal_result.confidence,
                "reasoning": temporal_result.reasoning,
                "method": "temporal_processing"
            }
        
        # For complex cases or low confidence, use LLM
        logging.info("Using LLM for complex lunch overtime processing")
        
        # Prepare date variables for the template
        current_date = get_this_day()
        tomorrow_date = current_date + timedelta(days=1)
        current_month_15 = current_date.replace(day=15)
        
        llm_chain = llm_lunch_overtime_template | gpt_4o_llm | lunch_overtime_parser
        llm_result = await llm_chain.ainvoke({
            "message": message,
            "current_date": current_date.isoformat(),
            "tomorrow_date": tomorrow_date.isoformat(),
            "current_month_15": current_month_15.isoformat()
        })
        
        logging.info(f"LLM processing result: {llm_result}")
        
        # Handle case where LLM returns a dict instead of LunchOvertimeInfo object
        if isinstance(llm_result, dict):
            date_obj = llm_result.get("date_obj")
            # Convert string date to date object if needed
            if isinstance(date_obj, str):
                from datetime import datetime
                date_obj = datetime.strptime(date_obj, "%Y-%m-%d").date()
            
            return {
                "status": "success",
                "date_obj": date_obj,
                "confidence": llm_result.get("confidence", 0.0),
                "reasoning": llm_result.get("reasoning", ""),
                "method": "llm_processing"
            }
        else:
            return {
                "status": "success",
                "date_obj": llm_result.date_obj,
                "confidence": llm_result.confidence,
                "reasoning": llm_result.reasoning,
                "method": "llm_processing"
            }
        
    except Exception as e:
        logging.error(f"Error processing lunch overtime: {e}")
        return {
            "status": "error",
            "message": f"Failed to process lunch overtime request: {str(e)}",
            "date_obj": None,
            "confidence": 0.0,
            "reasoning": f"Error: {str(e)}"
        }
