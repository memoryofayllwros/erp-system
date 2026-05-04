"""
Integrated temporal extraction system combining multiple methods
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
from src.utils.datetime_standarization_helpers import get_this_moment

# Import existing methods
from src.nlp_helpers.process_temporal_words import process_temporal_entities
from src.nlp_helpers.enhanced_temporal_extraction import enhanced_temporal_extraction
from src.nlp_helpers.ml_temporal_extraction import extract_temporal_ml
from src.nlp_helpers.llm_temporal_extraction import hybrid_temporal_extraction
from src.nlp_helpers.advanced_temporal_extraction import advanced_temporal_extraction

class IntegratedTemporalExtractor:
    """Integrated temporal extractor combining multiple methods"""
    
    def __init__(self):
        self.methods = {
            'rule_based': self._extract_rule_based,
            'enhanced_regex': self._extract_enhanced_regex,
            'ml_based': self._extract_ml_based,
            'llm_based': self._extract_llm_based,
            'advanced': self._extract_advanced
        }
    
    async def extract_temporal_comprehensive(self, text: str, use_methods: List[str] = None) -> Dict[str, Any]:
        """
        Comprehensive temporal extraction using multiple methods
        
        Args:
            text: Input text to analyze
            use_methods: List of methods to use (default: all)
            
        Returns:
            Dict containing results from all methods and consensus
        """
        if use_methods is None:
            use_methods = list(self.methods.keys())
        
        results = {}
        
        # Run all selected methods
        for method_name in use_methods:
            if method_name in self.methods:
                try:
                    if method_name == 'llm_based':
                        results[method_name] = await self.methods[method_name](text)
                    else:
                        results[method_name] = self.methods[method_name](text)
                except Exception as e:
                    logging.error(f"Error in {method_name} extraction: {str(e)}")
                    results[method_name] = {'error': str(e)}
        
        # Calculate consensus
        consensus = self._calculate_consensus(results)
        
        return {
            'individual_results': results,
            'consensus': consensus,
            'recommended_result': self._get_recommended_result(results, consensus)
        }
    
    def _extract_rule_based(self, text: str) -> Dict[str, Any]:
        """Rule-based extraction using existing method"""
        result = process_temporal_entities(text)
        return {
            'start_date': result.start_date,
            'end_date': result.end_date,
            'is_half_day': result.is_half_day,
            'time_period': result.time_period,
            'confidence': result.confidence,
            'entities_found': len(result.entities_found),
            'method': 'rule_based'
        }
    
    def _extract_enhanced_regex(self, text: str) -> Dict[str, Any]:
        """Enhanced regex extraction"""
        entities = enhanced_temporal_extraction(text)
        return {
            'entities': [entity.__dict__ for entity in entities],
            'entity_count': len(entities),
            'avg_confidence': sum(entity.confidence for entity in entities) / len(entities) if entities else 0,
            'method': 'enhanced_regex'
        }
    
    def _extract_ml_based(self, text: str) -> Dict[str, Any]:
        """ML-based extraction"""
        return extract_temporal_ml(text)
    
    async def _extract_llm_based(self, text: str) -> Dict[str, Any]:
        """LLM-based extraction"""
        return await hybrid_temporal_extraction(text)
    
    def _extract_advanced(self, text: str) -> Dict[str, Any]:
        """Advanced extraction using ensemble approach"""
        return advanced_temporal_extraction(text)
    
    def _calculate_consensus(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate consensus from multiple extraction methods"""
        consensus = {
            'start_date': None,
            'end_date': None,
            'is_half_day': False,
            'is_upper_half_day': None,
            'time_period': None,
            'confidence': 0.0,
            'agreement_score': 0.0
        }
        
        # Collect all start dates
        start_dates = []
        end_dates = []
        half_day_flags = []
        upper_half_flags = []
        time_periods = []
        confidences = []
        
        for method, result in results.items():
            if isinstance(result, dict) and 'error' not in result:
                if 'start_date' in result and result['start_date']:
                    start_dates.append(result['start_date'])
                if 'end_date' in result and result['end_date']:
                    end_dates.append(result['end_date'])
                if 'is_half_day' in result:
                    half_day_flags.append(result['is_half_day'])
                if 'is_upper_half_day' in result:
                    upper_half_flags.append(result['is_upper_half_day'])
                if 'time_period' in result and result['time_period']:
                    time_periods.append(result['time_period'])
                if 'confidence' in result:
                    confidences.append(result['confidence'])
        
        # Calculate consensus
        if start_dates:
            consensus['start_date'] = max(set(start_dates), key=start_dates.count)
        if end_dates:
            consensus['end_date'] = max(set(end_dates), key=end_dates.count)
        if half_day_flags:
            consensus['is_half_day'] = sum(half_day_flags) > len(half_day_flags) / 2
        if upper_half_flags:
            # Filter out None values
            valid_flags = [flag for flag in upper_half_flags if flag is not None]
            if valid_flags:
                consensus['is_upper_half_day'] = max(set(valid_flags), key=valid_flags.count)
        if time_periods:
            consensus['time_period'] = max(set(time_periods), key=time_periods.count)
        if confidences:
            consensus['confidence'] = sum(confidences) / len(confidences)
        
        # Calculate agreement score
        total_methods = len([r for r in results.values() if isinstance(r, dict) and 'error' not in r])
        if total_methods > 0:
            agreement_count = 0
            if consensus['start_date']:
                agreement_count += sum(1 for r in results.values() 
                                    if isinstance(r, dict) and r.get('start_date') == consensus['start_date'])
            consensus['agreement_score'] = agreement_count / total_methods
        
        return consensus
    
    def _get_recommended_result(self, results: Dict[str, Any], consensus: Dict[str, Any]) -> Dict[str, Any]:
        """Get the recommended result based on consensus and confidence"""
        # Find the method with highest confidence that agrees with consensus
        best_method = None
        best_score = 0.0
        
        for method, result in results.items():
            if isinstance(result, dict) and 'error' not in result:
                score = result.get('confidence', 0.0)
                
                # Bonus for agreement with consensus
                if (result.get('start_date') == consensus.get('start_date') and 
                    result.get('end_date') == consensus.get('end_date')):
                    score += 0.2
                
                if score > best_score:
                    best_score = score
                    best_method = method
        
        if best_method:
            recommended = results[best_method].copy()
            recommended['recommended_method'] = best_method
            recommended['consensus_agreement'] = consensus.get('agreement_score', 0.0)
            return recommended
        
        # Fallback to consensus
        return {
            **consensus,
            'recommended_method': 'consensus',
            'consensus_agreement': consensus.get('agreement_score', 0.0)
        }

# Specialized extractors for different use cases
class SickLeaveTemporalExtractor(IntegratedTemporalExtractor):
    """Specialized extractor for sick leave temporal information"""
    
    async def extract_sick_leave_temporal(self, text: str) -> Dict[str, Any]:
        """Extract temporal information specifically for sick leave requests"""
        # Use all methods but focus on sick leave context
        results = await self.extract_temporal_comprehensive(text)
        
        # Enhance with sick leave specific logic
        if results['consensus']['start_date']:
            # Validate that the date is reasonable (not too far in the past)
            try:
                start_date = datetime.strptime(results['consensus']['start_date'], '%Y-%m-%d')
                today = get_this_moment()
                if start_date < today - timedelta(days=30):
                    results['consensus']['confidence'] *= 0.5  # Reduce confidence for old dates
            except:
                pass
        
        return results

class AttendanceTemporalExtractor(IntegratedTemporalExtractor):
    """Specialized extractor for attendance temporal information"""
    
    async def extract_attendance_temporal(self, text: str) -> Dict[str, Any]:
        """Extract temporal information for attendance records"""
        results = await self.extract_temporal_comprehensive(text)
        
        # Attendance-specific validation
        if results['consensus']['start_date']:
            # For attendance, dates should typically be today or recent
            try:
                start_date = datetime.strptime(results['consensus']['start_date'], '%Y-%m-%d')
                today = get_this_moment()
                days_diff = (start_date - today).days
                
                if days_diff > 1:  # Future dates for attendance
                    results['consensus']['confidence'] *= 0.8
                elif days_diff < -7:  # Too far in the past
                    results['consensus']['confidence'] *= 0.6
            except:
                pass
        
        return results

# Main functions for easy integration
async def extract_temporal_integrated(text: str, context: str = None) -> Dict[str, Any]:
    """Main function for integrated temporal extraction"""
    extractor = IntegratedTemporalExtractor()
    return await extractor.extract_temporal_comprehensive(text)

async def extract_sick_leave_temporal_integrated(text: str) -> Dict[str, Any]:
    """Extract temporal information for sick leave with integrated methods"""
    extractor = SickLeaveTemporalExtractor()
    return await extractor.extract_sick_leave_temporal(text)

async def extract_attendance_temporal_integrated(text: str) -> Dict[str, Any]:
    """Extract temporal information for attendance with integrated methods"""
    extractor = AttendanceTemporalExtractor()
    return await extractor.extract_attendance_temporal(text)

async def extract_temporal_advanced_integrated(text: str) -> Dict[str, Any]:
    """Extract temporal information using only the advanced method"""
    extractor = IntegratedTemporalExtractor()
    return extractor._extract_advanced(text)
