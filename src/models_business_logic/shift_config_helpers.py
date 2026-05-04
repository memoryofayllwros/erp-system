from datetime import datetime, time
from typing import Optional, Tuple
import logging

from src.models.shift_config_model import Shift

class ShiftConfigHelper:
    """Helper class to work with dynamic shift configurations"""
    
    # Cache for loaded configurations (project_id -> Shift)
    _config_cache = {}
    
    @classmethod
    async def get_config(cls, project_id: str) -> Shift:
        """Get shift configuration for a project (with caching)"""
        if project_id in cls._config_cache:
            return cls._config_cache[project_id]
        
        config = await Shift.get_or_create_standard(project_id)
        cls._config_cache[project_id] = config
        return config
    
    @classmethod
    def clear_cache(cls, project_id: Optional[str] = None):
        """Clear configuration cache"""
        if project_id:
            cls._config_cache.pop(project_id, None)
        else:
            cls._config_cache.clear()
    
    @classmethod
    async def classify_shift(
        cls,
        shift_id: str,
        check_in_time: datetime,
        check_out_time: Optional[datetime] = None
    ) -> Tuple[Optional[str], str]:
        """
        Classify a shift using the project's configuration.
        
        Returns:
            Tuple of (shift_code, explanation_message)
        """
        config = await cls.get_config(shift_id)
        return config.classify_shift(check_in_time, check_out_time)
    
    @classmethod
    async def get_shift_configuration(
        cls,
        shift_id: str
    ) -> Optional[Shift]:
        """Get shift configuration for a project"""
        return await cls.get_config(shift_id)
    
    @classmethod
    async def get_shift_definition(
        cls,
        project_id: str,
        shift_code: str
    ) -> Optional[Shift]:
        """Get shift definition for a specific shift code"""
        config = await cls.get_config(project_id)
        return config.get_shift_definition(shift_code)
    
    @classmethod
    async def validate_check_in(
        cls,
        shift_id: str,
        check_in_time: time
    ) -> Tuple[bool, str]:
        try:
            shift_config = await cls.get_shift_configuration(shift_id)
            if not shift_config:
                return False, f"找不到更次定義: {shift_id}"
            
            # Validate that the hour is within the valid range (0-23)
            if check_in_time.hour < 0 or check_in_time.hour > 23:
                return False, f"無效的時間: 小時必須在 0..23 範圍內 (收到 {check_in_time.hour})"
            
            return True, "有效"
        except ValueError as e:
            logging.error(f"Time validation error in validate_check_in: {str(e)}")
            return False, f"時間格式錯誤: {str(e)}"
    

    @classmethod
    async def validate_check_out(
        cls,
        shift_id: str,
        check_out_time: time
    ) -> Tuple[bool, str]:
        try:
            shift_config = await cls.get_shift_configuration(shift_id)
            if not shift_config:
                return False, f"找不到更次定義: {shift_id}"
            
            # Validate that the hour is within the valid range (0-23)
            if check_out_time.hour < 0 or check_out_time.hour > 23:
                return False, f"無效的時間: 小時必須在 0..23 範圍內 (收到 {check_out_time.hour})"
            
            return True, "有效"
        except ValueError as e:
            logging.error(f"Time validation error in validate_check_out: {str(e)}")
            return False, f"時間格式錯誤: {str(e)}"




    @classmethod
    async def calculate_late_minutes(
        cls,
        project_id: str,
        shift_code: str,
        check_in_time: time
    ) -> int:
        """Calculate late minutes for check-in"""
        shift_def = await cls.get_shift_definition(project_id, shift_code)
        if not shift_def:
            return 0
        
        return shift_def.calculate_late_minutes(check_in_time)
    
    @classmethod
    async def calculate_early_minutes(
        cls,
        project_id: str,
        shift_code: str,
        check_out_time: time
    ) -> int:
        """Calculate early minutes for check-out"""
        shift_def = await cls.get_shift_definition(project_id, shift_code)
        if not shift_def:
            return 0
        
        return shift_def.calculate_early_minutes(check_out_time)
    
    @classmethod
    async def calculate_ot_hours(
        cls,
        project_id: str,
        shift_code: str,
        check_out_time: time
    ) -> float:
        """Calculate overtime hours"""
        shift_def = await cls.get_shift_definition(project_id, shift_code)
        if not shift_def:
            return 0.0
        
        return shift_def.calculate_ot_hours(check_out_time)
    
    @classmethod
    async def get_scheduled_times(
        cls,
        project_id: str,
        shift_code: str
    ) -> Tuple[Optional[time], Optional[time]]:
        """Get scheduled start and end times for a shift"""
        shift_def = await cls.get_shift_definition(project_id, shift_code)
        if not shift_def:
            return None, None
        
        return shift_def.scheduled_start, shift_def.scheduled_end
    
    @classmethod
    async def get_shift_display_name(
        cls,
        project_id: str,
        shift_code: str,
        language: str = "zh-hk"
    ) -> str:
        """Get display name for a shift"""
        shift_def = await cls.get_shift_definition(project_id, shift_code)
        if not shift_def:
            return shift_code
        
        return shift_def.get_display_name(language)
    
    @classmethod
    async def can_work_additional_shifts(
        cls,
        project_id: str,
        completed_shift_codes: list[str]
    ) -> bool:
        """Check if worker can do more shifts based on completed ones"""
        config = await cls.get_config(project_id)
        
        if not config.allow_multiple_shifts:
            return False
        
        if len(completed_shift_codes) >= config.max_shifts_per_day:
            return False
        
        return True
    
    @classmethod
    async def validate_shift_transition(
        cls,
        project_id: str,
        current_shift_code: str,
        new_check_in_time: datetime
    ) -> Tuple[bool, str]:
        """
        Validate if a new shift can be started after completing current shift.
        
        Returns:
            Tuple of (is_valid, explanation)
        """
        current_def = await cls.get_shift_definition(project_id, current_shift_code)
        if not current_def:
            return False, f"找不到當前更次定義: {current_shift_code}"
        
        # Classify what the new shift would be
        new_shift_code, message = await cls.classify_shift(
            project_id, new_check_in_time
        )
        
        if not new_shift_code:
            return False, message
        
        new_def = await cls.get_shift_definition(project_id, new_shift_code)
        if not new_def:
            return False, f"找不到新更次定義: {new_shift_code}"
        
        # Business logic: prevent overlapping shifts
        new_time = new_check_in_time.time()
        new_minutes = new_time.hour * 60 + new_time.minute
        
        # Simple rule: new shift must start after current shift's scheduled end
        current_end_minutes = (
            current_def.scheduled_end.hour * 60 + 
            current_def.scheduled_end.minute
        )
        
        if current_def.is_overnight:
            current_end_minutes += 24 * 60
        
        if new_minutes < current_end_minutes and not new_def.is_overnight:
            return False, (
                f"新更次簽到時間 {new_time.strftime('%H:%M')} 早於"
                f"當前更次預計結束時間 {current_def.scheduled_end.strftime('%H:%M')}"
            )
        
        return True, f"可以從 {current_def.get_display_name('zh-hk')} 轉到 {new_def.get_display_name('zh-hk')}"


# Convenience functions for direct use
async def classify_shift(
    project_id: str,
    check_in_time: datetime,
    check_out_time: Optional[datetime] = None
) -> Tuple[Optional[str], str]:
    """Convenience function to classify a shift"""
    return await ShiftConfigHelper.classify_shift(
        project_id, check_in_time, check_out_time
    )


async def get_shift_configuration(
    shift_id: str
) -> Optional[Shift]:
    """Convenience function to get shift configuration"""
    return await ShiftConfigHelper.get_shift_configuration(shift_id)


async def validate_check_in(
    shift_id: str,
    check_in_time: time
) -> Tuple[bool, str]:
    """Convenience function to validate check-in"""
    return await ShiftConfigHelper.validate_check_in(
        shift_id, check_in_time
    )


async def validate_check_out(
    shift_id: str,
    check_out_time: time
) -> Tuple[bool, str]:
    """Convenience function to validate check-out"""
    return await ShiftConfigHelper.validate_check_out(
        shift_id, check_out_time
    )