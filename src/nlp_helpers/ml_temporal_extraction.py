"""
Machine Learning-based temporal entity extraction
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from datetime import datetime, timedelta
import re
from src.utils.datetime_standarization_helpers import get_this_moment

class MLTemporalExtractor:
    """Machine Learning-based temporal entity extractor"""
    
    def __init__(self):
        # Feature extraction patterns
        self.feature_patterns = {
            'date_patterns': [
                r'\d{4}-\d{2}-\d{2}',  # ISO date
                r'\d{1,2}/\d{1,2}/\d{4}',  # US date
                r'\d{1,2}\.\d{1,2}\.\d{4}',  # European date
                r'\d{4}年\d{1,2}月\d{1,2}日',  # Chinese date
            ],
            'time_patterns': [
                r'\d{1,2}:\d{2}',  # Time
                r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)',  # 12-hour time
            ],
            'temporal_keywords': [
                '今天', '明天', '昨天', '後天', '前天',
                '下週', '本週', '上週', '下個月', '這個月', '上個月',
                '上午', '下午', '早上', '晚上', '中午',
                'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
                'next', 'this', 'last', 'tomorrow', 'today', 'yesterday'
            ]
        }
        
        # Contextual features
        self.context_features = {
            'leave_keywords': ['請假', '病假', '事假', '年假', 'leave', 'sick', 'vacation'],
            'attendance_keywords': ['報到', 'check in', 'attendance', '出勤', '上班'],
            'project_keywords': ['工程', 'project', '工作', 'work'],
            'time_indicators': ['開始', '結束', '到', 'from', 'to', 'until', 'since']
        }
    
    def extract_features(self, text: str) -> Dict[str, Any]:
        """Extract features for ML-based classification"""
        features = {}
        
        # Pattern-based features
        for pattern_type, patterns in self.feature_patterns.items():
            features[pattern_type] = []
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                features[pattern_type].extend(matches)
        
        # Contextual features
        for context_type, keywords in self.context_features.items():
            features[context_type] = sum(1 for keyword in keywords if keyword in text)
        
        # Text statistics
        features['text_length'] = len(text)
        features['word_count'] = len(text.split())
        features['has_numbers'] = bool(re.search(r'\d', text))
        features['has_chinese'] = bool(re.search(r'[\u4e00-\u9fff]', text))
        features['has_english'] = bool(re.search(r'[a-zA-Z]', text))
        
        return features
    
    def calculate_temporal_confidence(self, text: str, features: Dict[str, Any]) -> float:
        """Calculate confidence score for temporal content"""
        confidence = 0.0
        
        # Base confidence from pattern matches
        pattern_score = 0.0
        for pattern_type, matches in features.items():
            if isinstance(matches, list) and matches:
                pattern_score += len(matches) * 0.1
        
        confidence += min(pattern_score, 0.5)
        
        # Context boost
        context_score = 0.0
        for context_type, count in features.items():
            if isinstance(count, int) and count > 0:
                context_score += count * 0.1
        
        confidence += min(context_score, 0.3)
        
        # Language mixing bonus
        if features.get('has_chinese', False) and features.get('has_english', False):
            confidence += 0.1
        
        # Text length penalty (very short or very long text)
        text_length = features.get('text_length', 0)
        if text_length < 5:
            confidence -= 0.2
        elif text_length > 200:
            confidence -= 0.1
        
        return min(confidence, 1.0)
    
    def extract_temporal_entities_ml(self, text: str) -> List[Dict[str, Any]]:
        """Extract temporal entities using ML approach"""
        features = self.extract_features(text)
        confidence = self.calculate_temporal_confidence(text, features)
        
        entities = []
        
        # Extract entities based on features
        for pattern_type, matches in features.items():
            if isinstance(matches, list):
                for match in matches:
                    entity = {
                        'original_text': match,
                        'type': self._classify_entity_type(match),
                        'confidence': confidence,
                        'extraction_method': 'ml_features',
                        'features_used': pattern_type
                    }
                    entities.append(entity)
        
        return entities
    
    def _classify_entity_type(self, text: str) -> str:
        """Classify entity type based on text content"""
        if re.match(r'\d{4}-\d{2}-\d{2}', text):
            return 'date_iso'
        elif re.match(r'\d{1,2}/\d{1,2}/\d{4}', text):
            return 'date_us'
        elif re.match(r'\d{4}年\d{1,2}月\d{1,2}日', text):
            return 'date_chinese'
        elif re.match(r'\d{1,2}:\d{2}', text):
            return 'time'
        elif text in ['今天', '明天', '昨天', 'today', 'tomorrow', 'yesterday']:
            return 'relative_date'
        elif text in ['上午', '下午', '早上', '晚上', 'morning', 'afternoon', 'evening']:
            return 'time_period'
        else:
            return 'unknown'
    
    def ensemble_extraction(self, text: str) -> Dict[str, Any]:
        """Ensemble method combining multiple extraction approaches"""
        # ML-based extraction
        ml_entities = self.extract_temporal_entities_ml(text)
        
        # Rule-based extraction (import existing function)
        from src.nlp_helpers.process_temporal_words import process_temporal_entities
        rule_based_result = process_temporal_entities(text)
        
        # Combine results
        ensemble_result = {
            'ml_entities': ml_entities,
            'rule_based_result': {
                'start_date': rule_based_result.start_date,
                'end_date': rule_based_result.end_date,
                'is_half_day': rule_based_result.is_half_day,
                'confidence': rule_based_result.confidence
            },
            'ensemble_confidence': (len(ml_entities) * 0.1 + rule_based_result.confidence) / 2,
            'extraction_method': 'ensemble'
        }
        
        return ensemble_result

# Advanced ML-based temporal extraction with context awareness
class ContextAwareTemporalExtractor(MLTemporalExtractor):
    """Context-aware temporal extractor that considers conversation history"""
    
    def __init__(self):
        super().__init__()
        self.conversation_context = []
    
    def add_context(self, message: str, intent: str = None):
        """Add conversation context for better extraction"""
        self.conversation_context.append({
            'message': message,
            'intent': intent,
            'timestamp': get_this_moment()
        })
    
    def extract_with_context(self, text: str) -> Dict[str, Any]:
        """Extract temporal entities considering conversation context"""
        # Analyze recent context for temporal clues
        recent_context = self.conversation_context[-3:] if len(self.conversation_context) > 3 else self.conversation_context
        
        # Extract entities from current text
        current_entities = self.extract_temporal_entities_ml(text)
        
        # Analyze context for temporal references
        context_entities = []
        for ctx in recent_context:
            ctx_entities = self.extract_temporal_entities_ml(ctx['message'])
            context_entities.extend(ctx_entities)
        
        # Combine and deduplicate
        all_entities = current_entities + context_entities
        unique_entities = self._deduplicate_entities(all_entities)
        
        return {
            'current_entities': current_entities,
            'context_entities': context_entities,
            'combined_entities': unique_entities,
            'context_confidence': self._calculate_context_confidence(recent_context)
        }
    
    def _deduplicate_entities(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate entities"""
        seen = set()
        unique = []
        for entity in entities:
            key = entity['original_text']
            if key not in seen:
                seen.add(key)
                unique.append(entity)
        return unique
    
    def _calculate_context_confidence(self, context: List[Dict[str, Any]]) -> float:
        """Calculate confidence based on context"""
        if not context:
            return 0.0
        
        # Higher confidence if recent messages contain temporal references
        temporal_count = sum(1 for ctx in context if any(
            keyword in ctx['message'] for keyword in self.feature_patterns['temporal_keywords']
        ))
        
        return min(temporal_count * 0.2, 0.8)

# Usage functions
def extract_temporal_ml(text: str) -> Dict[str, Any]:
    """Main function for ML-based temporal extraction"""
    extractor = MLTemporalExtractor()
    return extractor.ensemble_extraction(text)

def extract_temporal_with_context(text: str, conversation_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract temporal entities with conversation context"""
    extractor = ContextAwareTemporalExtractor()
    
    if conversation_history:
        for msg in conversation_history:
            extractor.add_context(msg.get('message', ''), msg.get('intent'))
    
    return extractor.extract_with_context(text)
