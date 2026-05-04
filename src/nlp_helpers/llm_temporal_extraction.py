"""
LLM-based temporal entity extraction for improved accuracy
"""
import logging
from typing import List, Dict, Any, Optional
from src.utils.datetime_standarization_helpers import get_this_moment

# This would integrate with the existing LLM setup
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

class LLMTemporalEntity(BaseModel):
    """Temporal entity extracted by LLM"""
    original_text: str = Field(description="The original text that was identified as temporal")
    entity_type: str = Field(description="Type of temporal entity (date, time, duration, etc.)")
    normalized_value: str = Field(description="Normalized value of the entity")
    confidence: float = Field(description="Confidence score between 0 and 1")
    start_date: Optional[str] = Field(description="Start date in YYYY-MM-DD format if applicable")
    end_date: Optional[str] = Field(description="End date in YYYY-MM-DD format if applicable")
    is_half_day: bool = Field(description="Whether this is a half-day event")
    time_period: Optional[str] = Field(description="Time period (morning, afternoon, etc.)")

class LLMTemporalExtraction(BaseModel):
    """Complete temporal extraction result from LLM"""
    entities: List[LLMTemporalEntity] = Field(description="List of extracted temporal entities")
    overall_confidence: float = Field(description="Overall confidence in the extraction")
    extraction_notes: str = Field(description="Notes about the extraction process")

# LLM prompt for temporal extraction
llm_temporal_extraction_prompt = PromptTemplate(
    template="""
You are an expert at extracting temporal information from Chinese and English text. 
Your task is to identify and extract all temporal entities from the given text.

Current date and time: {current_datetime}

Text to analyze: "{text}"

Please extract all temporal entities including:
1. Dates (absolute and relative)
2. Times (specific times and time periods)
3. Durations
4. Day of week references
5. Relative time expressions (today, tomorrow, next week, etc.)

For each entity, provide:
- The original text
- Entity type (date, time, duration, day_of_week, relative_time)
- Normalized value
- Confidence score (0-1)
- Start and end dates if applicable
- Whether it's a half-day event
- Time period if applicable

Pay special attention to:
- Chinese temporal expressions (今天, 明天, 下週一, etc.)
- Mixed language text
- Context clues that indicate temporal intent
- Relative dates that need to be calculated from the current date

Return the results in the specified JSON format.
""",
    input_variables=["text", "current_datetime"]
)

# Output parser
temporal_extraction_parser = PydanticOutputParser(pydantic_object=LLMTemporalExtraction)

# Create the LLM chain
temporal_extraction_chain = llm_temporal_extraction_prompt | gpt_4o_llm | temporal_extraction_parser

async def extract_temporal_with_llm(text: str) -> LLMTemporalExtraction:
    """
    Extract temporal entities using LLM for improved accuracy
    
    Args:
        text: Input text to analyze
        
    Returns:
        LLMTemporalExtraction: Structured temporal extraction results
    """
    try:
        current_datetime = get_this_moment().strftime("%Y-%m-%d %H:%M:%S")
        
        result = await temporal_extraction_chain.ainvoke({
            "text": text,
            "current_datetime": current_datetime
        })
        
        logging.info(f"LLM temporal extraction result: {result}")
        return result
        
    except Exception as e:
        logging.error(f"Error in LLM temporal extraction: {str(e)}")
        return LLMTemporalExtraction(
            entities=[],
            overall_confidence=0.0,
            extraction_notes=f"Error: {str(e)}"
        )

async def hybrid_temporal_extraction(text: str) -> Dict[str, Any]:
    """
    Hybrid approach combining rule-based and LLM-based extraction
    
    Args:
        text: Input text to analyze
        
    Returns:
        Dict containing both rule-based and LLM results with confidence scores
    """
    from src.nlp_helpers.process_temporal_words import process_temporal_entities
    
    # Rule-based extraction
    rule_based_result = process_temporal_entities(text)
    
    # LLM-based extraction
    llm_result = await extract_temporal_with_llm(text)
    
    # Combine results
    combined_result = {
        "rule_based": {
            "start_date": rule_based_result.start_date,
            "end_date": rule_based_result.end_date,
            "is_half_day": rule_based_result.is_half_day,
            "time_period": rule_based_result.time_period,
            "confidence": rule_based_result.confidence,
            "entities_found": len(rule_based_result.entities_found)
        },
        "llm_based": {
            "entities": [entity.dict() for entity in llm_result.entities],
            "overall_confidence": llm_result.overall_confidence,
            "extraction_notes": llm_result.extraction_notes
        },
        "combined_confidence": (rule_based_result.confidence + llm_result.overall_confidence) / 2,
        "recommended_approach": "llm" if llm_result.overall_confidence > rule_based_result.confidence else "rule_based"
    }
    
    return combined_result

# Specialized LLM prompts for different temporal contexts
sick_leave_temporal_prompt = PromptTemplate(
    template="""
You are analyzing a sick leave request. Extract temporal information with high precision.

Current date: {current_date}

Sick leave text: "{text}"

Focus on:
1. Leave start and end dates
2. Half-day indicators (上午半天, 下午半天, etc.)
3. Duration of leave
4. Any medical certificate requirements

Extract and normalize all temporal information. Pay special attention to:
- Chinese temporal expressions
- Relative dates (next Monday, tomorrow, etc.)
- Half-day indicators
- Duration expressions

Return structured temporal information.
""",
    input_variables=["text", "current_date"]
)

async def extract_sick_leave_temporal(text: str) -> Dict[str, Any]:
    """Specialized extraction for sick leave temporal information"""
    try:
        current_date = get_this_moment().strftime("%Y-%m-%d")
        
        result = await sick_leave_temporal_prompt.ainvoke({
            "text": text,
            "current_date": current_date
        })
        
        return result
        
    except Exception as e:
        logging.error(f"Error in sick leave temporal extraction: {str(e)}")
        return {"error": str(e)}
