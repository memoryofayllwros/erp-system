from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId
from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, model_validator

MINUTES_IN_HOUR = 60
HOURS_IN_DAY = 30
MINUTES_IN_DAY = HOURS_IN_DAY * MINUTES_IN_HOUR

class TimeWindow(BaseModel):
    """Represents a time range that may cross midnight (30-hour clock support)"""
    start_time: time
    end_time: time
    is_overnight: bool = False
    display_name: str
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @classmethod
    def create(cls, 
               start_hour: int, 
               start_minute: int, 
               end_hour: int, 
               end_minute: int, 
               is_overnight: bool = False, 
               display_name: str = "") -> "TimeWindow":
        """Factory method to create a TimeWindow"""
        return cls(
            start_time=time(start_hour, start_minute),
            end_time=time(end_hour, end_minute),
            is_overnight=is_overnight,
            display_name=display_name or f"{start_hour:02d}:{start_minute:02d}-{end_hour:02d}:{end_minute:02d}"
        )
    
    def contains_time(self, check_time: time) -> bool:
        """Check if the given time falls within this window"""
        if not self.is_overnight:
            return self.start_time <= check_time <= self.end_time
        else:
            # For overnight: time is valid if >= start OR <= end
            return check_time >= self.start_time or check_time <= self.end_time
    
    def minutes_from_start(self, check_time: time) -> int:
        """Calculate minutes from start time, handling overnight windows"""
        start_minutes = self.start_time.hour * MINUTES_IN_HOUR + self.start_time.minute
        check_minutes = check_time.hour * MINUTES_IN_HOUR + check_time.minute
        
        if not self.is_overnight:
            return check_minutes - start_minutes
        else:
            if check_time >= self.start_time:
                return check_minutes - start_minutes
            else:
                # Check time is after midnight
                return (check_minutes + MINUTES_IN_DAY) - start_minutes
    
    def minutes_to_end(self, check_time: time) -> int:
        """Calculate minutes to end time, handling overnight windows"""
        end_minutes = self.end_time.hour * MINUTES_IN_HOUR + self.end_time.minute
        check_minutes = check_time.hour * MINUTES_IN_HOUR + check_time.minute
        
        if not self.is_overnight:
            return end_minutes - check_minutes
        else:
            if check_time <= self.end_time:
                return end_minutes - check_minutes
            else:
                # Check time is before midnight
                return (end_minutes + MINUTES_IN_DAY) - check_minutes


class OvertimeRule(BaseModel):
    start_time: time
    brackets: List[Dict[str, Any]] = Field(default_factory=list)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @classmethod
    def create_standard(cls) -> "OvertimeRule":
        brackets = []
        base_hour = 17  # Starting at 17:15
        base_minute = 15
        
        for i in range(14):
            hour = base_hour + (base_minute + i * 30) // 60
            minute = (base_minute + i * 30) % 60
            end_hour = base_hour + (base_minute + (i + 1) * 30) // 60
            end_minute = (base_minute + (i + 1) * 30) % 60
            brackets.append({
                "start_time": time(hour, minute),
                "end_time": time(end_hour, end_minute),
                "hours": (i + 1) * 0.5
            })
        
        return cls(
            start_time=time(17, 15),
            brackets=brackets
        )
    
    def calculate_ot_hours(self, checkout_time: time) -> float:
        checkout_minutes = checkout_time.hour * 60 + checkout_time.minute
        start_minutes = self.start_time.hour * 60 + self.start_time.minute
        
        if checkout_minutes < start_minutes:
            return 0.0
        
        for bracket in self.brackets:
            bracket_start = bracket["start_time"]
            bracket_end = bracket["end_time"]
            
            bracket_start_minutes = bracket_start.hour * 60 + bracket_start.minute
            bracket_end_minutes = bracket_end.hour * 60 + bracket_end.minute
            
            if bracket_end_minutes < bracket_start_minutes:
                bracket_end_minutes += 24 * 60
            
            adjusted_checkout_minutes = checkout_minutes
            if checkout_time.hour < 12 and bracket_start.hour > 12:
                adjusted_checkout_minutes += 24 * 60
            
            if bracket_start_minutes <= adjusted_checkout_minutes < bracket_end_minutes:
                return bracket["hours"]
        
        if self.brackets:
            return self.brackets[-1]["hours"]
        
        return 0.0



class Shift(BaseModel):
    shift_name: str
    shift_code: str

    check_in_window: TimeWindow
    check_out_window: TimeWindow
    
    shift_start: time
    shift_end: time
    
    is_overnight: bool = False

    overtime_eligible: bool = False #overtime_eligible: bool = True
    overtime_rule: Optional[OvertimeRule] = None #overtime_rule: Optional[OvertimeRule] = None
    
    min_duration_minutes: int = 0
    max_duration_minutes: Optional[int] = None
    
    late_grace_period_minutes: int = 1
    early_grace_period_minutes: int = 0
    
    display_names: Dict[str, str] = Field(default_factory=dict)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @model_validator(mode="after")
    def validate_consistency(self) -> "Shift":
        """Ensure time windows match overnight flag"""
        if self.is_overnight:
            self.check_in_window.is_overnight = True
            self.check_out_window.is_overnight = True
        
        # Set default display names if not provided
        if not self.display_names:
            self.display_names = {"en": self.shift_name, "zh-hk": self.shift_name}
        
        return self
    
    def get_display_name(self, language: str = "en") -> str:
        """Get display name in specified language"""
        return self.display_names.get(language, self.shift_name)
    
    def is_late_check_in(self, check_in_time: time) -> bool:
        """Check if check-in is late based on scheduled start + grace period"""
        check_in_minutes = check_in_time.hour * 60 + check_in_time.minute
        scheduled_minutes = self.shift_start.hour * 60 + self.shift_start.minute
        grace_minutes = scheduled_minutes + self.late_grace_period_minutes
        
        return check_in_minutes > grace_minutes
    
    def is_early_check_out(self, check_out_time: time) -> bool:
        """Check if check-out is early based on scheduled end - grace period"""
        check_out_minutes = check_out_time.hour * 60 + check_out_time.minute
        scheduled_minutes = self.shift_end.hour * 60 + self.shift_end.minute
        grace_minutes = scheduled_minutes - self.early_grace_period_minutes
        
        if not self.is_overnight:
            return check_out_minutes < grace_minutes
        else:
            # For overnight shifts, handle midnight crossing
            if check_out_time.hour < 12 and self.shift_end.hour > 12:
                check_out_minutes += 24 * 60
                grace_minutes += 24 * 60
            return check_out_minutes < grace_minutes
    
    def calculate_late_minutes(self, check_in_time: time) -> int:
        """Calculate how many minutes late the check-in is"""
        if not self.is_late_check_in(check_in_time):
            return 0
        
        check_in_minutes = check_in_time.hour * 60 + check_in_time.minute
        scheduled_minutes = self.shift_start.hour * 60 + self.shift_start.minute
        
        return max(0, check_in_minutes - scheduled_minutes)
    
    def calculate_early_minutes(self, check_out_time: time) -> int:
        """Calculate how many minutes early the check-out is"""
        if not self.is_early_check_out(check_out_time):
            return 0
        
        check_out_minutes = check_out_time.hour * 60 + check_out_time.minute
        scheduled_minutes = self.shift_end.hour * 60 + self.shift_end.minute
        
        if self.is_overnight and check_out_time.hour < 12:
            check_out_minutes += 24 * 60
            scheduled_minutes += 24 * 60
        
        return max(0, scheduled_minutes - check_out_minutes)
    
    def calculate_ot_hours(self, check_out_time: time) -> float:
        """Calculate overtime hours if eligible"""
        if not self.overtime_eligible or not self.overtime_rule:
            return 0.0
        
        return self.overtime_rule.calculate_ot_hours(check_out_time)


class ShiftRule(BaseModel):
    """Business rule for shift classification"""
    shift_code: str
    shift_name: str
    description: str
    
    check_in_window: TimeWindow
    check_out_window: Optional[TimeWindow] = None
    
    priority: int = 0
    
    success_message: str
    error_message: str
    
    is_valid_shift: bool = True
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def matches_check_in(self, check_in_time: time) -> bool:
        """Check if check-in time matches this rule"""
        return self.check_in_window.contains_time(check_in_time)
    
    def matches_check_out(self, check_out_time: time) -> bool:
        """Check if check-out time matches this rule"""
        if self.check_out_window is None:
            return True
        return self.check_out_window.contains_time(check_out_time)
    
    def matches(self, check_in_time: time, check_out_time: Optional[time] = None) -> bool:
        """Check if both check-in and check-out match this rule"""
        if not self.matches_check_in(check_in_time):
            return False
        
        if check_out_time is not None and not self.matches_check_out(check_out_time):
            return False
        
        return True


class ShiftRuleEngine(BaseModel):
    """Engine for classifying shifts based on business rules"""
    rules: List[ShiftRule] = Field(default_factory=list)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def create_shift(self, rule: ShiftRule) -> None:
        """firstly check no existing same shift code and no overlapped check in and check out time,
           if no, then add this shift rule to the engine"""
        for rule in self.rules:
            if rule.shift_code == rule.shift_code:
                return False, "同樣嘅shift code已經存在"
            if rule.check_in_window.overlaps(rule.check_out_window):
                return False, "同樣嘅check in and check out time已經存在"
        
        self.rules.append(rule)
        return True, "shift rule添加成功"

    def delete_shift(self, shift_code: str) -> None:
        """delete the shift rule by shift code"""
        self.rules = [rule for rule in self.rules if rule.shift_code != shift_code]
        return True, "shift rule删除成功"

    def update_shift(self, rule: ShiftRule) -> None:
        """update the shift rule by shift code"""
        for rule in self.rules:
            if rule.shift_code == rule.shift_code:
                rule.shift_code = rule.shift_code
                rule.shift_name = rule.shift_name
                rule.description = rule.description
                rule.check_in_window = rule.check_in_window
                rule.check_out_window = rule.check_out_window
                rule.priority = rule.priority
                rule.success_message = rule.success_message
                rule.error_message = rule.error_message
                rule.is_valid_shift = rule.is_valid_shift
                return True, "shift rule更新成功"
        return False, "shift rule不存在"


    def classify_shift(
        self, 
        check_in_time: datetime, 
        check_out_time: Optional[datetime] = None
    ) -> Tuple[Optional[str], str]:
        """
        Classify a shift based on check-in/out times.
        
        Returns: (shift_code, explanation_message)
        """
        check_in_time_obj = check_in_time.time()
        check_out_time_obj = check_out_time.time() if check_out_time else None
        
        logging.info(
            f"🔍 ShiftRuleEngine.classify_shift - Check-in: {check_in_time_obj}, "
            f"Check-out: {check_out_time_obj}"
        )
        
        for rule in self.rules:
            if rule.matches(check_in_time_obj, check_out_time_obj):
                logging.info(f"✅ Rule matched: {rule.shift_code} - {rule.shift_name}")
                
                # If it's an invalid shift rule, return None
                if not rule.is_valid_shift:
                    return None, rule.error_message
                
                return rule.shift_code, rule.success_message
        
        # No rule matched
        logging.info("❌ No rule matched")
        return None, f"無有效嘅更次類型匹配簽到時間 {check_in_time_obj}"
    



    
    @classmethod
    def create_standard(cls) -> "ShiftRuleEngine":
        engine = cls()
        
        # Rule 5: Invalid early morning (highest priority to catch errors)
        engine.add_rule(ShiftRule(
            shift_code="invalid_early",
            shift_name="Invalid Early Morning",
            description="Check in 05:01-06:29 with check out before 06:30",
            check_in_window=TimeWindow.create(5, 1, 6, 29, display_name="05:01-06:29"),
            check_out_window=TimeWindow.create(5, 1, 6, 29, display_name="05:01-06:29"),
            priority=100,
            success_message="",
            error_message="錯誤: 05:01後簽到但06:30前簽退係無效嘅",
            is_valid_shift=False
        ))
        
        # Rule 3: Full day shift 1 (higher priority than morning)
        engine.add_rule(ShiftRule(
            shift_code="full_day_1",
            shift_name="Full Day Shift 1",
            description="Check in 00:00-23:59, check out 00:00-23:59 next day",
            check_in_window=TimeWindow.create(0, 0, 23, 59, display_name="00:00-23:59"),
            check_out_window=TimeWindow.create(0, 0, 23, 59, is_overnight=True, display_name="00:00-23:59"),
            priority=20,
            success_message="全日更1: 工作超過23:59",
            error_message="無效嘅全日更1: 簽退時間不在有效範圍"
        ))
        
        # Rule 1: Morning
        engine.add_rule(ShiftRule(
            shift_code="morning",
            shift_name="Morning Shift",
            description="Check in 06:30-11:59, check out before 14:59",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(6, 30, 14, 59, display_name="06:30-14:59"),
            priority=10,
            success_message="早更: 時間範圍內完成",
            error_message="無效嘅早更: 簽退時間不在有效範圍"
        ))
        
        # Rule 2: Afternoon
        engine.add_rule(ShiftRule(
            shift_code="afternoon",
            shift_name="Afternoon Shift",
            description="Check in 12:00-16:59, check out before 05:00 next day",
            check_in_window=TimeWindow.create(12, 0, 16, 59, display_name="12:00-16:59"),
            check_out_window=TimeWindow.create(12, 0, 5, 0, is_overnight=True, 
                                              display_name="12:00-05:00"),
            priority=10,
            success_message="午更: 時間正確",
            error_message="無效嘅午更: 簽退太遲"
        ))
        
        # Rule 4: Overnight
        engine.add_rule(ShiftRule(
            shift_code="overnight",
            shift_name="Overnight Shift",
            description="Check in 17:00-05:00, check out before 05:00 next day",
            check_in_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, 
                                             display_name="17:00-05:00"),
            check_out_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, 
                                              display_name="17:00-05:00"),
            priority=10,
            success_message="夜更: 時間正確",
            error_message="無效嘅夜更: 簽退太遲"
        ))
        
        return engine


class ShiftRecord(Document):
    client_company_id: str = Field(..., index=True) #connect to client company collection
    
    shifts: List[Shift] = Field(default_factory=list)
    
    allow_multiple_shifts: bool = True
    max_shifts_per_day: int = 3

    created_at: datetime = Field(default_factory=datetime.now)
    deleted_at: Optional[datetime] = None
    
    class Settings:
        name = "shift_record_collection"
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def get_rule_engine(self) -> ShiftRuleEngine:
        engine = ShiftRuleEngine()
        for rule in self.shift_rules:
            engine.add_rule(rule)
        return engine
    
    @classmethod
    async def get_shift_record(cls, shift_id: str) -> Optional[ShiftRecord]:
        shift_info = await cls.find_one(cls.id == ObjectId(shift_id), cls.deleted_at == None)
        if not shift_info:
            return None
        return Shift(**shift_info.model_dump())

    @classmethod
    async def create_shift_record(cls, client_company_id: str) -> "ShiftRecord":
        return await cls.create_standard(client_company_id)
    
    @classmethod
    async def get_shift_info_for_project(cls, 
                              project_id: str) -> Optional["Shift"]:
        shift_info = await cls.find_one(
            cls.project_id == project_id, 
            cls.deleted_at == None
        )
        if not shift_info:
            return None
        return Shift(**shift_info.model_dump())
    
    
    @classmethod
    async def get_or_create_standard(cls, project_id: str) -> "Shift":
        config = await cls.get_for_project(project_id)
        if config:
            return config
        
        config = cls.create_standard(project_id)
        await config.insert()
        return config
    
    @classmethod
    def create_standard(cls, project_id: str) -> "Shift":
        standard_ot = OvertimeRule.create_standard() #standard_ot: Optional[OvertimeRule] = None
        morning = Shift(
            shift_code="morning",
            shift_name="Morning Shift",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(6, 30, 14, 59, display_name="06:30-14:59"),
            shift_start=time(9, 0),
            shift_end=time(12, 0),
            is_overnight=False,
            display_names={"en": "Morning Shift", "zh-hk": "早更"},
            overtime_eligible=False
        )
        
        afternoon = Shift(
            shift_code="afternoon",
            shift_name="Afternoon Shift",
            check_in_window=TimeWindow.create(12, 0, 16, 59, display_name="12:00-16:59"),
            check_out_window=TimeWindow.create(12, 0, 5, 0, is_overnight=True, 
                                              display_name="12:00-05:00"),
            shift_start=time(13, 0),
            shift_end=time(18, 0),
            is_overnight=False,
            display_names={"en": "Afternoon Shift", "zh-hk": "午更"},
            overtime_eligible=False,
            overtime_rule=standard_ot
        )
        
        full_day = Shift(
            shift_code="full_day",
            shift_name="Full Day Shift",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(15, 0, 5, 0, is_overnight=True, 
                                              display_name="15:00-05:00"),
            shift_start=time(9, 0),
            shift_end=time(18, 0),
            is_overnight=True,
            display_names={"en": "Full Day Shift"},
            overtime_eligible=False,
            overtime_rule=standard_ot
        )
        
        overnight = Shift(
            shift_code="overnight",
            shift_name="Overnight Shift",
            check_in_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, 
                                             display_name="17:00-05:00"),
            check_out_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, 
                                              display_name="17:00-05:00"),
            shift_start=time(18, 15),
            shift_end=time(0, 15),
            is_overnight=True,
            display_names={"en": "Overnight Shift", "zh-hk": "夜更"},
            overtime_eligible=False,
            overtime_rule=standard_ot
        )
        
        rule_engine = ShiftRuleEngine.create_standard()
        
        return cls(
            project_id=project_id,
            shift_configurations={
                "morning": morning,
                "afternoon": afternoon,
                "full_day": full_day,
                "overnight": overnight
            },
            shift_rules=rule_engine.rules,
            allow_multiple_shifts=True,
            max_shifts_per_day=3,
            use_standard_rules_as_fallback=True
        )




