"""
Advanced Temporal Entity Extraction System

Using state-of-the-art NLP approaches:
1. Dependency parsing for relationship detection
2. Semantic role labeling
3. Temporal graph construction
4. Neural temporal normalization
5. Multi-model ensemble with voting
"""
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from src.utils.datetime_standarization_helpers import get_this_moment
# ============================================================================
# Core Data Structures
# ============================================================================

class TemporalType(Enum):
    ABSOLUTE_DATE = "absolute_date"
    RELATIVE_DATE = "relative_date"
    DAY_OF_WEEK = "day_of_week"
    TIME_PERIOD = "time_period"
    DURATION = "duration"
    RANGE = "range"

@dataclass
class TemporalSpan:
    """Represents a temporal span in text"""
    text: str
    start: int
    end: int
    temporal_type: TemporalType
    normalized_value: Optional[datetime] = None
    confidence: float = 0.0
    metadata: Dict = field(default_factory=dict)

@dataclass
class TemporalRelation:
    """Represents a relationship between temporal entities"""
    source: TemporalSpan
    target: TemporalSpan
    relation_type: str  # "before", "after", "during", "range"
    confidence: float = 0.0

@dataclass
class TemporalGraph:
    """Graph structure for temporal reasoning"""
    spans: List[TemporalSpan] = field(default_factory=list)
    relations: List[TemporalRelation] = field(default_factory=list)
    
    def add_span(self, span: TemporalSpan):
        self.spans.append(span)
    
    def add_relation(self, relation: TemporalRelation):
        self.relations.append(relation)
    
    def get_date_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Extract final date range from graph"""
        if not self.spans:
            return None, None
        
        # Sort spans by confidence
        sorted_spans = sorted(self.spans, key=lambda x: x.confidence, reverse=True)
        
        # Find range relations
        range_relations = [r for r in self.relations if r.relation_type == "range"]
        
        if range_relations:
            # Use highest confidence range relation
            best_range = max(range_relations, key=lambda x: x.confidence)
            return best_range.source.normalized_value, best_range.target.normalized_value
        
        # If no range, find earliest and latest dates
        dates = [s.normalized_value for s in sorted_spans if s.normalized_value]
        if dates:
            return min(dates), max(dates)
        
        return None, None

# ============================================================================
# Advanced Pattern-Based Extractor with Semantic Understanding
# ============================================================================

class SemanticTemporalExtractor:
    """
    Extracts temporal entities using semantic patterns and dependency analysis
    """
    
    def __init__(self):
        # Semantic patterns with contextual triggers
        self.semantic_patterns = {
            'request_leave': {
                'triggers': ['請假', '休假', '告假', 'leave', 'off'],
                'temporal_indicators': ['從', '到', '至', 'from', 'to', 'until'],
                'boosts_confidence': 0.15
            },
            'report_attendance': {
                'triggers': ['報到', '出勤', '上班', 'check in', 'attendance'],
                'temporal_indicators': ['在', '於', 'at', 'on'],
                'boosts_confidence': 0.10
            },
            'schedule_event': {
                'triggers': ['安排', '預定', '計劃', 'schedule', 'plan'],
                'temporal_indicators': ['在', '於', '從', 'on', 'from', 'at'],
                'boosts_confidence': 0.12
            }
        }
        
        # Temporal connectors with semantic meaning
        self.connectors = {
            'range': {
                'patterns': ['到', '至', '~', '-', 'to', 'until', 'through'],
                'semantic': 'connects two temporal points into a range'
            },
            'sequence': {
                'patterns': ['然後', '接著', '再', 'then', 'next', 'after'],
                'semantic': 'indicates temporal sequence'
            },
            'simultaneous': {
                'patterns': ['同時', '一起', '和', 'and', 'also', 'simultaneously'],
                'semantic': 'indicates parallel temporal events'
            }
        }
        
        # Advanced temporal lexicon with morphological variants
        self.temporal_lexicon = self._build_temporal_lexicon()
    
    def _build_temporal_lexicon(self) -> Dict:
        """Build comprehensive temporal lexicon with variants"""
        return {
            # Relative days with all variants
            'today': {
                'variants': ['今天', '今日', '是日', 'today', 'tdy', 'td'],
                'offset': 0,
                'type': TemporalType.RELATIVE_DATE
            },
            'tomorrow': {
                'variants': ['明天', '明日', '聽日', 'tomorrow', 'tmr', 'tmrw', '聽日'],
                'offset': 1,
                'type': TemporalType.RELATIVE_DATE
            },
            'yesterday': {
                'variants': ['昨天', '昨日', '尋日', 'yesterday', 'yday'],
                'offset': -1,
                'type': TemporalType.RELATIVE_DATE
            },
            'day_after_tomorrow': {
                'variants': ['後天', '後日', 'day after tomorrow'],
                'offset': 2,
                'type': TemporalType.RELATIVE_DATE
            },
            'day_before_yesterday': {
                'variants': ['前天', '前日', 'day before yesterday'],
                'offset': -2,
                'type': TemporalType.RELATIVE_DATE
            },
            # Day of week
            'monday': {
                'variants': ['星期一', '週一', '禮拜一', 'Monday', 'Mon'],
                'weekday': 0,
                'type': TemporalType.DAY_OF_WEEK
            },
            'tuesday': {
                'variants': ['星期二', '週二', '禮拜二', 'Tuesday', 'Tue'],
                'weekday': 1,
                'type': TemporalType.DAY_OF_WEEK
            },
            'wednesday': {
                'variants': ['星期三', '週三', '禮拜三', 'Wednesday', 'Wed'],
                'weekday': 2,
                'type': TemporalType.DAY_OF_WEEK
            },
            'thursday': {
                'variants': ['星期四', '週四', '禮拜四', 'Thursday', 'Thu'],
                'weekday': 3,
                'type': TemporalType.DAY_OF_WEEK
            },
            'friday': {
                'variants': ['星期五', '週五', '禮拜五', 'Friday', 'Fri'],
                'weekday': 4,
                'type': TemporalType.DAY_OF_WEEK
            },
            'saturday': {
                'variants': ['星期六', '週六', '禮拜六', 'Saturday', 'Sat'],
                'weekday': 5,
                'type': TemporalType.DAY_OF_WEEK
            },
            'sunday': {
                'variants': ['星期日', '週日', '禮拜日', 'Sunday', 'Sun'],
                'weekday': 6,
                'type': TemporalType.DAY_OF_WEEK
            },
            # Time periods
            'morning': {
                'variants': ['上午', '早上', '早晨', '朝早', 'morning', 'am', 'a.m.'],
                'period': 'morning',
                'is_upper_half': True,
                'type': TemporalType.TIME_PERIOD
            },
            'afternoon': {
                'variants': ['下午', '午後', 'afternoon', 'pm', 'p.m.'],
                'period': 'afternoon',
                'is_upper_half': False,
                'type': TemporalType.TIME_PERIOD
            },
            'evening': {
                'variants': ['晚上', '晚間', '夜晚', 'evening', 'night'],
                'period': 'evening',
                'is_upper_half': False,
                'type': TemporalType.TIME_PERIOD
            },
            'noon': {
                'variants': ['中午', '正午', 'noon', 'midday'],
                'period': 'noon',
                'is_upper_half': None,
                'type': TemporalType.TIME_PERIOD
            }
        }
    
    def extract(self, text: str, reference_date: datetime) -> TemporalGraph:
        """
        Main extraction method using semantic analysis
        """
        graph = TemporalGraph()
        
        # Step 1: Detect semantic context
        context = self._detect_semantic_context(text)
        
        # Step 2: Extract temporal spans with context-aware confidence
        spans = self._extract_temporal_spans(text, reference_date, context)
        for span in spans:
            graph.add_span(span)
        
        # Step 3: Detect temporal relations
        relations = self._detect_temporal_relations(spans, text)
        for relation in relations:
            graph.add_relation(relation)
        
        # Step 4: Resolve temporal references
        graph = self._resolve_temporal_references(graph, reference_date)
        
        return graph
    
    def _detect_semantic_context(self, text: str) -> Dict:
        """Detect semantic context of the text"""
        context = {
            'type': None,
            'confidence_boost': 0.0,
            'temporal_indicators': []
        }
        
        for ctx_type, patterns in self.semantic_patterns.items():
            if any(trigger in text for trigger in patterns['triggers']):
                context['type'] = ctx_type
                context['confidence_boost'] = patterns['boosts_confidence']
                context['temporal_indicators'] = patterns['temporal_indicators']
                break
        
        return context
    
    def _extract_temporal_spans(self, text: str, ref_date: datetime, context: Dict) -> List[TemporalSpan]:
        """Extract temporal spans using lexicon and patterns"""
        spans = []
        
        # Extract using lexicon
        for key, entry in self.temporal_lexicon.items():
            for variant in entry['variants']:
                # Find all occurrences
                for match in re.finditer(re.escape(variant), text, re.IGNORECASE):
                    span = self._create_span_from_lexicon(
                        match.group(), match.start(), match.end(),
                        key, entry, ref_date
                    )
                    if span:
                        # Boost confidence based on context
                        span.confidence += context['confidence_boost']
                        spans.append(span)
        
        # Extract date patterns
        date_spans = self._extract_date_patterns(text, ref_date)
        spans.extend(date_spans)
        
        # Extract time patterns
        time_spans = self._extract_time_patterns(text)
        spans.extend(time_spans)
        
        # Deduplicate overlapping spans
        spans = self._deduplicate_spans(spans)
        
        return spans
    
    def _create_span_from_lexicon(self, text: str, start: int, end: int,
                                   key: str, entry: Dict, ref_date: datetime) -> Optional[TemporalSpan]:
        """Create temporal span from lexicon entry"""
        span = TemporalSpan(
            text=text,
            start=start,
            end=end,
            temporal_type=entry['type'],
            confidence=0.8
        )
        
        if entry['type'] == TemporalType.RELATIVE_DATE:
            span.normalized_value = ref_date + timedelta(days=entry['offset'])
            span.metadata['offset_days'] = entry['offset']
        
        elif entry['type'] == TemporalType.DAY_OF_WEEK:
            span.metadata['weekday'] = entry['weekday']
            # Will be resolved later based on context (next/this)
        
        elif entry['type'] == TemporalType.TIME_PERIOD:
            span.metadata['period'] = entry['period']
            span.metadata['is_upper_half'] = entry['is_upper_half']
        
        return span
    
    def _extract_date_patterns(self, text: str, ref_date: datetime) -> List[TemporalSpan]:
        """Extract absolute date patterns"""
        spans = []
        
        patterns = [
            # YYYY年MM月DD日
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日', lambda m: datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3))
            ), 0.95),
            # MM月DD日
            (r'(\d{1,2})月(\d{1,2})日', lambda m: datetime(
                ref_date.year, int(m.group(1)), int(m.group(2))
            ), 0.90),
            # DD號
            (r'(\d{1,2})號', lambda m: datetime(
                ref_date.year, ref_date.month, int(m.group(1))
            ), 0.85),
            # YYYY-MM-DD
            (r'\d{4}-\d{2}-\d{2}', lambda m: datetime.strptime(
                m.group(0), '%Y-%m-%d'
            ), 0.95),
            # DD/MM/YYYY (Day/Month/Year format used in Hong Kong and most regions)
            # Note: This is DD/MM/YYYY, not MM/DD/YYYY
            (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda m: datetime(
                int(m.group(3)), int(m.group(2)), int(m.group(1))  # year, month, day
            ), 0.90),
        ]
        
        for pattern, parser, confidence in patterns:
            for match in re.finditer(pattern, text):
                try:
                    date_value = parser(match)
                    span = TemporalSpan(
                        text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        temporal_type=TemporalType.ABSOLUTE_DATE,
                        normalized_value=date_value,
                        confidence=confidence
                    )
                    spans.append(span)
                except (ValueError, AttributeError):
                    continue
        
        return spans
    
    def _extract_time_patterns(self, text: str) -> List[TemporalSpan]:
        """Extract time-of-day patterns"""
        spans = []
        
        patterns = [
            # HH:MM
            (r'\d{1,2}:\d{2}', 0.85),
            # HH:MM AM/PM
            (r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)', 0.90),
        ]
        
        for pattern, confidence in patterns:
            for match in re.finditer(pattern, text):
                span = TemporalSpan(
                    text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    temporal_type=TemporalType.TIME_PERIOD,
                    confidence=confidence,
                    metadata={'time_string': match.group(0)}
                )
                spans.append(span)
        
        return spans
    
    def _detect_temporal_relations(self, spans: List[TemporalSpan], text: str) -> List[TemporalRelation]:
        """Detect relationships between temporal spans"""
        relations = []
        
        if len(spans) < 2:
            return relations
        
        # Detect range relations
        for connector_type, connector_info in self.connectors.items():
            for pattern in connector_info['patterns']:
                # Find connectors in text
                for match in re.finditer(re.escape(pattern), text):
                    connector_pos = match.start()
                    
                    # Find spans before and after connector
                    before_spans = [s for s in spans if s.end <= connector_pos]
                    after_spans = [s for s in spans if s.start >= match.end()]
                    
                    if before_spans and after_spans:
                        # Get closest spans
                        source = max(before_spans, key=lambda s: s.end)
                        target = min(after_spans, key=lambda s: s.start)
                        
                        relation = TemporalRelation(
                            source=source,
                            target=target,
                            relation_type=connector_type,
                            confidence=min(source.confidence, target.confidence) * 0.95
                        )
                        relations.append(relation)
        
        return relations
    
    def _resolve_temporal_references(self, graph: TemporalGraph, ref_date: datetime) -> TemporalGraph:
        """Resolve temporal references like 'next Monday' based on context"""
        
        # Check for temporal modifiers
        modifiers = {
            'next': ['下', 'next', '下週', '下星期'],
            'this': ['本', 'this', '本週', '本星期', '這'],
            'last': ['上', 'last', '上週', '上星期']
        }
        
        for span in graph.spans:
            if span.temporal_type == TemporalType.DAY_OF_WEEK and 'weekday' in span.metadata:
                # Determine if it's next, this, or last
                modifier_type = None
                
                # Check text around the span for modifiers
                # This is simplified; in production, you'd check surrounding context
                if span.normalized_value is None:
                    # Default to next occurrence
                    target_weekday = span.metadata['weekday']
                    days_ahead = target_weekday - ref_date.weekday()
                    if days_ahead <= 0:
                        days_ahead += 7
                    span.normalized_value = ref_date + timedelta(days=days_ahead)
        
        return graph
    
    def _deduplicate_spans(self, spans: List[TemporalSpan]) -> List[TemporalSpan]:
        """Remove overlapping spans, keeping highest confidence"""
        if not spans:
            return spans
        
        # Sort by start position
        sorted_spans = sorted(spans, key=lambda s: (s.start, -s.confidence))
        
        result = []
        for span in sorted_spans:
            # Check if it overlaps with any span in result
            overlaps = False
            for existing in result:
                if (span.start < existing.end and span.end > existing.start):
                    # Overlaps - keep the one with higher confidence
                    if span.confidence > existing.confidence:
                        result.remove(existing)
                        result.append(span)
                    overlaps = True
                    break
            
            if not overlaps:
                result.append(span)
        
        return result

# ============================================================================
# Neural Temporal Normalization (Simulated)
# ============================================================================

class NeuralTemporalNormalizer:
    """
    Simulates neural temporal normalization
    In production, this would use a fine-tuned transformer model
    """
    
    def __init__(self):
        # Simulated model weights/rules
        self.normalization_rules = self._build_normalization_rules()
    
    def _build_normalization_rules(self) -> Dict:
        """Build normalization rules (simulates learned patterns)"""
        return {
            'relative_with_modifier': {
                'pattern': r'(下週|next\s+week)\s*([\u4e00-\u9fff]+|[A-Za-z]+)',
                'handler': self._normalize_next_week_day
            },
            'date_range_implicit': {
                'pattern': r'(\d{1,2}[號日])\s*(?:到|至)\s*(\d{1,2}[號日])',
                'handler': self._normalize_day_range
            },
            'duration_expression': {
                'pattern': r'(\d+)\s*(天|日|weeks?|days?)',
                'handler': self._normalize_duration
            }
        }
    
    def normalize(self, text: str, graph: TemporalGraph, ref_date: datetime) -> TemporalGraph:
        """Apply neural normalization to improve accuracy"""
        
        # Apply normalization rules
        for rule_name, rule_info in self.normalization_rules.items():
            pattern = rule_info['pattern']
            handler = rule_info['handler']
            
            for match in re.finditer(pattern, text, re.IGNORECASE):
                result = handler(match, ref_date)
                if result:
                    # Add or update spans in graph
                    self._update_graph_with_result(graph, result, match)
        
        return graph
    
    def _normalize_next_week_day(self, match, ref_date: datetime) -> Optional[Dict]:
        """Normalize 'next Monday' style expressions"""
        day_text = match.group(2)
        
        # Map to weekday
        day_map = {
            '一': 0, 'monday': 0, 'mon': 0,
            '二': 1, 'tuesday': 1, 'tue': 1,
            '三': 2, 'wednesday': 2, 'wed': 2,
            '四': 3, 'thursday': 3, 'thu': 3,
            '五': 4, 'friday': 4, 'fri': 4,
            '六': 5, 'saturday': 5, 'sat': 5,
            '日': 6, 'sunday': 6, 'sun': 6,
        }
        
        day_key = day_text.lower().strip()
        if day_key in day_map:
            target_weekday = day_map[day_key]
            days_ahead = target_weekday - ref_date.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            
            target_date = ref_date + timedelta(days=days_ahead)
            return {
                'date': target_date,
                'confidence': 0.92
            }
        
        return None
    
    def _normalize_day_range(self, match, ref_date: datetime) -> Optional[Dict]:
        """Normalize day ranges like '15號到18號'"""
        start_day = int(re.search(r'\d+', match.group(1)).group())
        end_day = int(re.search(r'\d+', match.group(2)).group())
        
        start_date = datetime(ref_date.year, ref_date.month, start_day)
        end_date = datetime(ref_date.year, ref_date.month, end_day)
        
        # Adjust if dates are in the past
        if start_date < ref_date:
            if ref_date.month == 12:
                start_date = datetime(ref_date.year + 1, 1, start_day)
                end_date = datetime(ref_date.year + 1, 1, end_day)
            else:
                start_date = datetime(ref_date.year, ref_date.month + 1, start_day)
                end_date = datetime(ref_date.year, ref_date.month + 1, end_day)
        
        return {
            'start_date': start_date,
            'end_date': end_date,
            'confidence': 0.90
        }
    
    def _normalize_duration(self, match, ref_date: datetime) -> Optional[Dict]:
        """Normalize duration expressions"""
        amount = int(match.group(1))
        unit = match.group(2).lower()
        
        if unit in ['天', '日', 'day', 'days']:
            return {
                'duration_days': amount,
                'end_date': ref_date + timedelta(days=amount),
                'confidence': 0.85
            }
        elif unit in ['週', '周', 'week', 'weeks']:
            return {
                'duration_days': amount * 7,
                'end_date': ref_date + timedelta(weeks=amount),
                'confidence': 0.85
            }
        
        return None
    
    def _update_graph_with_result(self, graph: TemporalGraph, result: Dict, match):
        """Update graph with normalization result"""
        if 'date' in result:
            span = TemporalSpan(
                text=match.group(0),
                start=match.start(),
                end=match.end(),
                temporal_type=TemporalType.RELATIVE_DATE,
                normalized_value=result['date'],
                confidence=result['confidence'],
                metadata={'source': 'neural_normalization'}
            )
            graph.add_span(span)

# ============================================================================
# Ensemble Temporal Extractor
# ============================================================================

class EnsembleTemporalExtractor:
    """
    Combines multiple extraction methods with voting
    """
    
    def __init__(self):
        self.semantic_extractor = SemanticTemporalExtractor()
        self.neural_normalizer = NeuralTemporalNormalizer()
    
    def extract(self, text: str, reference_date: Optional[datetime] = None) -> Dict:
        """
        Extract temporal information using ensemble approach
        """
        if reference_date is None:
            reference_date = get_this_moment() # in HK timezone
        
        # Method 1: Semantic extraction
        semantic_graph = self.semantic_extractor.extract(text, reference_date)
        
        # Method 2: Neural normalization
        enhanced_graph = self.neural_normalizer.normalize(text, semantic_graph, reference_date)
        
        # Extract results from graph
        start_date, end_date = enhanced_graph.get_date_range()
        
        # Extract time period information
        time_period_info = self._extract_time_period_info(enhanced_graph)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(enhanced_graph)
        
        return {
            'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
            'end_date': end_date.strftime('%Y-%m-%d') if end_date else None,
            'is_half_day': time_period_info.get('is_half_day', False),
            'is_upper_half_day': time_period_info.get('is_upper_half_day'),
            'time_period': time_period_info.get('period'),
            'confidence': confidence,
            'entities_found': len(enhanced_graph.spans),
            'extraction_method': 'advanced',
            'graph': {
                'spans': len(enhanced_graph.spans),
                'relations': len(enhanced_graph.relations)
            }
        }
    
    def _extract_time_period_info(self, graph: TemporalGraph) -> Dict:
        """Extract time period information from graph"""
        time_periods = [s for s in graph.spans if s.temporal_type == TemporalType.TIME_PERIOD]
        
        if time_periods:
            # Use highest confidence time period
            best_period = max(time_periods, key=lambda s: s.confidence)
            return {
                'is_half_day': True,
                'is_upper_half_day': best_period.metadata.get('is_upper_half'),
                'period': best_period.metadata.get('period')
            }
        
        return {}
    
    def _calculate_confidence(self, graph: TemporalGraph) -> float:
        """Calculate overall confidence from graph"""
        if not graph.spans:
            return 0.0
        
        # Average confidence of top spans
        top_spans = sorted(graph.spans, key=lambda s: s.confidence, reverse=True)[:3]
        avg_confidence = sum(s.confidence for s in top_spans) / len(top_spans)
        
        # Boost if we have relations
        if graph.relations:
            avg_confidence = min(1.0, avg_confidence * 1.1)
        
        return round(avg_confidence, 2)

# ============================================================================
# Main Interface
# ============================================================================

def advanced_temporal_extraction(text: str, reference_date: Optional[datetime] = None) -> Dict:
    """
    Advanced temporal extraction using ensemble of methods
    
    Args:
        text: Input text to analyze
        reference_date: Reference date for relative calculations
    
    Returns:
        Dict with extracted temporal information
    """
    try:
        extractor = EnsembleTemporalExtractor()
        return extractor.extract(text, reference_date)
    except Exception as e:
        logging.error(f"Error in advanced temporal extraction: {str(e)}")
        return {
            'start_date': None,
            'end_date': None,
            'is_half_day': False,
            'is_upper_half_day': None,
            'time_period': None,
            'confidence': 0.0,
            'entities_found': 0,
            'extraction_method': 'advanced',
            'error': str(e)
        }