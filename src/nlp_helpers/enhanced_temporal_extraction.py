"""
Enhanced temporal entity extraction with multiple methods for improved accuracy
"""
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import difflib

@dataclass
class EnhancedTemporalEntity:
    original_text: str
    type: str
    category: str
    normalized_value: str
    confidence: float
    start_pos: int
    end_pos: int
    extraction_method: str

class EnhancedTemporalExtractor:
    """Enhanced temporal entity extractor with multiple extraction methods"""
    
    def __init__(self):
        # Enhanced regex patterns for better temporal extraction
        self.patterns = {
            # Date patterns
            'date_iso': r'\b(\d{4}-\d{2}-\d{2})\b',
            'date_slash': r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
            'date_dot': r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b',
            'date_chinese': r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            'date_simple': r'(\d{1,2})月(\d{1,2})日',
            'date_day_only': r'(\d{1,2})號',
            
            # Time patterns
            'time_24h': r'\b(\d{1,2}:\d{2})\b',
            'time_12h': r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm|上午|下午))\b',
            'time_period': r'(上午|下午|早上|晚上|中午|凌晨)',
            
            # Relative time patterns
            'relative_days': r'(今天|明天|昨天|後天|前天|大後天|大前天)',
            'relative_weeks': r'(這週|本週|下週|上週|這星期|下星期|上星期)',
            'relative_months': r'(這個月|本月|下個月|上個月)',
            'relative_years': r'(今年|明年|去年|後年|前年)',
            
            # Day of week patterns
            'day_of_week': r'(星期一|星期二|星期三|星期四|星期五|星期六|星期日|週一|週二|週三|週四|週五|週六|週日|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)',
            'next_day': r'(下週一|下週二|下週三|下週四|下週五|下週六|下週日|下星期一|下星期二|下星期三|下星期四|下星期五|下星期六|下星期日|next Monday|next Tuesday|next Wednesday|next Thursday|next Friday|next Saturday|next Sunday)',
            'this_day': r'(本週一|本週二|本週三|本週四|本週五|本週六|本週日|本星期一|本星期二|本星期三|本星期四|本星期五|本星期六|本星期日|this Monday|this Tuesday|this Wednesday|this Thursday|this Friday|this Saturday|this Sunday)',
            
            # Duration patterns
            'duration_days': r'(\d+天|\d+日)',
            'duration_weeks': r'(\d+週|\d+星期|\d+周)',
            'duration_months': r'(\d+個月|\d+月)',
            'duration_years': r'(\d+年)',
            
            # Half day patterns
            'half_day': r'(半天|半日|上午半天|下午半天|早上半天|晚上半天)',
        }
        
        # Contextual keywords that help identify temporal intent
        self.temporal_context_keywords = [
            '請假', '病假', '事假', '年假', 'leave', 'sick', 'vacation',
            '開始', '結束', '到', 'from', 'to', 'until', 'since',
            '報到', 'check in', 'attendance', '出勤'
        ]
    
    def extract_with_regex(self, text: str) -> List[EnhancedTemporalEntity]:
        """Extract temporal entities using enhanced regex patterns"""
        entities = []
        
        for pattern_name, pattern in self.patterns.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                entity = EnhancedTemporalEntity(
                    original_text=match.group(),
                    type=self._get_entity_type(pattern_name),
                    category=self._get_entity_category(pattern_name),
                    normalized_value=self._normalize_value(match.group(), pattern_name),
                    confidence=self._calculate_regex_confidence(match.group(), pattern_name),
                    start_pos=match.start(),
                    end_pos=match.end(),
                    extraction_method="regex"
                )
                entities.append(entity)
        
        return entities
    
    def extract_with_context_analysis(self, text: str) -> List[EnhancedTemporalEntity]:
        """Extract temporal entities using context analysis"""
        entities = []
        
        # Check for temporal context
        has_temporal_context = any(keyword in text for keyword in self.temporal_context_keywords)
        if not has_temporal_context:
            return entities
        
        # Look for temporal expressions near context keywords
        words = text.split()
        for i, word in enumerate(words):
            if word in self.temporal_context_keywords:
                # Check surrounding words for temporal expressions
                context_window = words[max(0, i-3):min(len(words), i+4)]
                context_text = ' '.join(context_window)
                
                # Extract entities from context
                context_entities = self.extract_with_regex(context_text)
                for entity in context_entities:
                    entity.confidence *= 1.2  # Boost confidence due to context
                    entity.extraction_method = "context_analysis"
                    entities.append(entity)
        
        return entities
    
    def extract_with_fuzzy_matching(self, text: str, reference_entities: List[str]) -> List[EnhancedTemporalEntity]:
        """Extract temporal entities using fuzzy string matching"""
        entities = []
        
        for ref_entity in reference_entities:
            # Find best fuzzy matches
            matches = difflib.get_close_matches(
                ref_entity, 
                text.split(), 
                n=3, 
                cutoff=0.6
            )
            
            for match in matches:
                similarity = difflib.SequenceMatcher(None, ref_entity, match).ratio()
                if similarity > 0.6:
                    entity = EnhancedTemporalEntity(
                        original_text=match,
                        type="time",
                        category="fuzzy_match",
                        normalized_value=ref_entity,
                        confidence=similarity,
                        start_pos=text.find(match),
                        end_pos=text.find(match) + len(match),
                        extraction_method="fuzzy_matching"
                    )
                    entities.append(entity)
        
        return entities
    
    def extract_with_llm_enhancement(self, text: str, base_entities: List[EnhancedTemporalEntity]) -> List[EnhancedTemporalEntity]:
        """Enhance extraction results using LLM-based validation"""
        enhanced_entities = []
        
        for entity in base_entities:
            # Use LLM to validate and enhance entity
            enhanced_entity = self._validate_with_llm(entity, text)
            if enhanced_entity:
                enhanced_entities.append(enhanced_entity)
        
        return enhanced_entities
    
    def extract_with_confidence_ranking(self, text: str) -> List[EnhancedTemporalEntity]:
        """Extract entities using multiple methods and rank by confidence"""
        all_entities = []
        
        # Method 1: Regex extraction
        regex_entities = self.extract_with_regex(text)
        all_entities.extend(regex_entities)
        
        # Method 2: Context analysis
        context_entities = self.extract_with_context_analysis(text)
        all_entities.extend(context_entities)
        
        # Method 3: Fuzzy matching (if reference entities available)
        # This would require a reference list of temporal entities
        
        # Remove duplicates and rank by confidence
        unique_entities = self._deduplicate_entities(all_entities)
        ranked_entities = sorted(unique_entities, key=lambda x: x.confidence, reverse=True)
        
        return ranked_entities
    
    def _get_entity_type(self, pattern_name: str) -> str:
        """Map pattern name to entity type"""
        type_mapping = {
            'date_iso': 'time', 'date_slash': 'time', 'date_dot': 'time',
            'date_chinese': 'time', 'date_simple': 'time', 'date_day_only': 'time',
            'time_24h': 'time', 'time_12h': 'time', 'time_period': 'time_period',
            'relative_days': 'time', 'relative_weeks': 'time_range', 'relative_months': 'time_range',
            'day_of_week': 'time', 'next_day': 'time', 'this_day': 'time',
            'duration_days': 'time_range', 'duration_weeks': 'time_range',
            'half_day': 'time_period'
        }
        return type_mapping.get(pattern_name, 'time')
    
    def _get_entity_category(self, pattern_name: str) -> str:
        """Map pattern name to entity category"""
        category_mapping = {
            'date_iso': 'absolute_date', 'date_slash': 'absolute_date', 'date_dot': 'absolute_date',
            'date_chinese': 'absolute_date', 'date_simple': 'absolute_date', 'date_day_only': 'absolute_date',
            'time_24h': 'time', 'time_12h': 'time', 'time_period': 'day_segment',
            'relative_days': 'relative_date', 'relative_weeks': 'relative_range',
            'day_of_week': 'day_of_week', 'next_day': 'relative_day_of_week',
            'duration_days': 'duration', 'half_day': 'day_segment'
        }
        return category_mapping.get(pattern_name, 'unknown')
    
    def _normalize_value(self, text: str, pattern_name: str) -> str:
        """Normalize extracted text based on pattern type"""
        # This would contain logic to normalize different temporal expressions
        # For now, return the text as-is
        return text.lower()
    
    def _calculate_regex_confidence(self, text: str, pattern_name: str) -> float:
        """Calculate confidence score for regex-extracted entities"""
        base_confidence = 0.8
        
        # Adjust confidence based on pattern specificity
        if 'date_iso' in pattern_name:
            return 0.95
        elif 'date_chinese' in pattern_name:
            return 0.9
        elif 'relative_days' in pattern_name:
            return 0.85
        elif 'day_of_week' in pattern_name:
            return 0.8
        
        return base_confidence
    
    def _validate_with_llm(self, entity: EnhancedTemporalEntity, text: str) -> Optional[EnhancedTemporalEntity]:
        """Validate entity using LLM (placeholder for future implementation)"""
        # This would use an LLM to validate the extracted entity
        # For now, return the entity as-is
        return entity
    
    def _deduplicate_entities(self, entities: List[EnhancedTemporalEntity]) -> List[EnhancedTemporalEntity]:
        """Remove duplicate entities, keeping the one with highest confidence"""
        entity_map = {}
        
        for entity in entities:
            key = (entity.original_text, entity.start_pos, entity.end_pos)
            if key not in entity_map or entity.confidence > entity_map[key].confidence:
                entity_map[key] = entity
        
        return list(entity_map.values())

def enhanced_temporal_extraction(text: str) -> List[EnhancedTemporalEntity]:
    """Main function for enhanced temporal extraction"""
    extractor = EnhancedTemporalExtractor()
    return extractor.extract_with_confidence_ranking(text)
