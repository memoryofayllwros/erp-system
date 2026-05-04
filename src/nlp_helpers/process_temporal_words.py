from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel
import json
import os

# Load temporal entities from JSON file
def load_temporal_entities():
    json_path = os.path.join(os.path.dirname(__file__), 'temporal_entities.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['temporal_entities']

temporal_entities = load_temporal_entities()
import logging
from datetime import datetime, timedelta
import re
from src.utils.datetime_standarization_helpers import get_this_moment

def get_next_weekday(current_date: datetime, day_name: str) -> datetime:
    """Get the next occurrence of a specific weekday"""
    # Map day names to weekday numbers (Monday=0, Sunday=6)
    day_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    
    target_weekday = day_map.get(day_name.lower())
    if target_weekday is None:
        return current_date
    
    # Calculate days until next occurrence
    days_ahead = target_weekday - current_date.weekday()
    if days_ahead <= 0:  # Target day already passed this week
        days_ahead += 7
    
    return current_date + timedelta(days=days_ahead)

def get_this_weekday(current_date: datetime, day_name: str) -> datetime:
    """Get this week's occurrence of a specific weekday, or next week if it already passed"""
    # Map day names to weekday numbers (Monday=0, Sunday=6)
    day_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    
    target_weekday = day_map.get(day_name.lower())
    if target_weekday is None:
        return current_date
    
    # Calculate days until this week's occurrence
    days_ahead = target_weekday - current_date.weekday()
    if days_ahead < 0:  # Target day already passed this week, get next week's
        days_ahead += 7
    
    return current_date + timedelta(days=days_ahead)

class TemporalEntity(BaseModel):
    original_text: str
    type: Literal["time", "time_range", "date_range", "time_period"]
    category: str
    normalized_value: Optional[str] = None
    confidence: float = 1.0

class ProcessedTemporalInfo(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_half_day: bool = False
    is_upper_half_day: Optional[bool] = None
    time_period: Optional[str] = None
    confidence: float = 0.0
    entities_found: List[TemporalEntity] = []

def extract_temporal_entities(message: str) -> List[TemporalEntity]:
    """Extract temporal entities from message with improved matching"""
    results = []
    message_lower = message.lower()
    
    for entity in temporal_entities:
        # Check for exact match first
        if entity["zh"] in message:
            results.append(TemporalEntity(
                original_text=entity["zh"],
                type=entity["type"],
                category=entity["category"],
                normalized_value=entity["normalized"],
                confidence=1.0
            ))
        # Check for partial matches with lower confidence
        elif entity["zh"] in message_lower:
            results.append(TemporalEntity(
                original_text=entity["zh"],
                type=entity["type"],
                category=entity["category"],
                normalized_value=entity["normalized"],
                confidence=0.8
            ))
    
    logging.info(f"Extracted temporal entities: {results}")
    return results

def process_temporal_entities(message: str) -> ProcessedTemporalInfo:
    """Process temporal entities and extract structured date/time information"""
    # Check for direct date format in the message (e.g., "compensatory leave, 2025-10-27")
    date_pattern = r'\d{4}-\d{2}-\d{2}'
    direct_date_matches = re.findall(date_pattern, message)
    
    if direct_date_matches:
        if len(direct_date_matches) >= 2:
            # We have at least two dates - use first as start_date and last as end_date
            start_date = direct_date_matches[0]
            end_date = direct_date_matches[-1]
            logging.info(f"Extracted date range: {start_date} to {end_date}")
            return ProcessedTemporalInfo(
                start_date=start_date,
                end_date=end_date,
                confidence=1.0
            )
        else:
            # Only one date found - use for both start and end
            date_str = direct_date_matches[0]
            return ProcessedTemporalInfo(
                start_date=date_str,
                end_date=date_str,
                confidence=1.0
            )
    
    entities = extract_temporal_entities(message)
    
    if not entities:
        return ProcessedTemporalInfo(confidence=0.0)
    
    # Get current date for relative date calculations
    now = get_this_moment()
    today = now.strftime("%Y-%m-%d")
    
    # Initialize result
    result = ProcessedTemporalInfo(
        entities_found=entities,
        confidence=0.0
    )
    
    # Check for range indicators in the message
    range_indicators = ["到", "至", "to", "until", "from", "從"]
    has_range_indicator = any(indicator in message for indicator in range_indicators)
    
    # Collect day-of-week entities for potential range processing
    day_of_week_entities = []
    time_range_entities = []
    
    # First pass: collect entities by type
    for entity in entities:
        if entity.type == "time" and entity.category == "day_of_week":
            day_of_week_entities.append(entity)
        elif entity.type == "time_range" and entity.category == "relative_range":
            time_range_entities.append(entity)
    
    # Check if we have a potential date range (multiple day-of-week entities with range indicator)
    if has_range_indicator and len(day_of_week_entities) >= 2:
        # For Chinese text like "下週一到下週三", we expect the first entity to be the start
        # and the last entity to be the end
        start_entity = day_of_week_entities[0]
        end_entity = day_of_week_entities[-1]
        
        # Calculate dates for start and end
        start_date = get_next_weekday(now, start_entity.normalized_value)
        end_date = get_next_weekday(now, end_entity.normalized_value)
        
        # Ensure end_date is not before start_date
        if end_date < start_date:
            # If end date is before start date, it means we need to go to next week
            end_date = end_date + timedelta(weeks=1)
        
        result.start_date = start_date.strftime("%Y-%m-%d")
        result.end_date = end_date.strftime("%Y-%m-%d")
        result.confidence = max(start_entity.confidence, end_entity.confidence)
        
        logging.info(f"Detected date range: {result.start_date} to {result.end_date}")
    else:
        # Process entities individually (original logic)
        for entity in entities:
            normalized = entity.normalized_value
            
            if entity.type == "time" and entity.category == "relative_date":
                if normalized == "today":
                    result.start_date = today
                    result.end_date = today
                    result.confidence = max(result.confidence, entity.confidence)
                elif normalized == "tomorrow":
                    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                    result.start_date = tomorrow
                    result.end_date = tomorrow
                    result.confidence = max(result.confidence, entity.confidence)
                elif normalized == "yesterday":
                    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                    result.start_date = yesterday
                    result.end_date = yesterday
                    result.confidence = max(result.confidence, entity.confidence)
                elif normalized == "day_after_tomorrow":
                    day_after = (now + timedelta(days=2)).strftime("%Y-%m-%d")
                    result.start_date = day_after
                    result.end_date = day_after
                    result.confidence = max(result.confidence, entity.confidence)
                elif normalized == "day_before_yesterday":
                    day_before = (now - timedelta(days=2)).strftime("%Y-%m-%d")
                    result.start_date = day_before
                    result.end_date = day_before
                    result.confidence = max(result.confidence, entity.confidence)
            
            elif entity.type == "time_period" and entity.category == "day_segment":
                result.is_half_day = True
                result.time_period = normalized
                if normalized == "morning":
                    result.is_upper_half_day = True
                elif normalized == "afternoon":
                    result.is_upper_half_day = False
                result.confidence = max(result.confidence, entity.confidence)
            
            elif entity.type == "time" and entity.category == "day_of_week":
                # Handle specific day of week (e.g., "Monday", "Tuesday")
                target_date = get_next_weekday(now, normalized)
                result.start_date = target_date.strftime("%Y-%m-%d")
                result.end_date = result.start_date
                result.confidence = max(result.confidence, entity.confidence)
            
            elif entity.type == "time" and entity.category == "relative_day_of_week":
                # Handle relative day of week (e.g., "next Monday", "this Tuesday")
                if normalized.startswith("next_"):
                    day_name = normalized.replace("next_", "")
                    target_date = get_next_weekday(now, day_name)
                    result.start_date = target_date.strftime("%Y-%m-%d")
                    result.end_date = result.start_date
                    result.confidence = max(result.confidence, entity.confidence)
                elif normalized.startswith("this_"):
                    day_name = normalized.replace("this_", "")
                    target_date = get_this_weekday(now, day_name)
                    result.start_date = target_date.strftime("%Y-%m-%d")
                    result.end_date = result.start_date
                    result.confidence = max(result.confidence, entity.confidence)
    
    # Check for half-day indicators in the message
    half_day_indicators = ["半天", "半日", "上午", "下午", "早上", "晚上"]
    for indicator in half_day_indicators:
        if indicator in message:
            result.is_half_day = True
            if indicator in ["上午", "早上"]:
                result.is_upper_half_day = True
            elif indicator in ["下午", "晚上"]:
                result.is_upper_half_day = False
            result.confidence = max(result.confidence, 0.9)
            break
    
    # If no specific dates found, try to extract from the message using regex
    if not result.start_date:
        date_patterns = [
            r'(\d{1,2})號',  # "15號"
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',  # "2025年1月15日"
            r'(\d{1,2})月(\d{1,2})日',  # "1月15日"
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, message)
            if match:
                try:
                    if len(match.groups()) == 1:  # "15號"
                        day = int(match.group(1))
                        result.start_date = f"{now.year}-{now.month:02d}-{day:02d}"
                        result.end_date = result.start_date
                        result.confidence = 0.8
                    elif len(match.groups()) == 3:  # "2025年1月15日"
                        year, month, day = map(int, match.groups())
                        result.start_date = f"{year}-{month:02d}-{day:02d}"
                        result.end_date = result.start_date
                        result.confidence = 0.9
                    elif len(match.groups()) == 2:  # "1月15日"
                        month, day = map(int, match.groups())
                        result.start_date = f"{now.year}-{month:02d}-{day:02d}"
                        result.end_date = result.start_date
                        result.confidence = 0.8
                    break
                except ValueError:
                    continue
    
    # If we still don't have dates, default to today
    if not result.start_date:
        result.start_date = today
        result.end_date = today
        result.confidence = 0.5
    
    logging.info(f"Processed temporal info: {result}")
    return result
