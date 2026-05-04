from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MINUTES_IN_HOUR = 60
HOURS_IN_DAY = 30
MINUTES_IN_DAY = HOURS_IN_DAY * MINUTES_IN_HOUR


class TimeWindow(BaseModel):
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

        return cls(
            start_time=time(start_hour, start_minute),
            end_time=time(end_hour, end_minute),
            is_overnight=is_overnight,
            display_name=display_name or f"{start_hour:02d}:{start_minute:02d}-{end_hour:02d}:{end_minute:02d}"
        )
    
    def contains_time(self, check_time: time) -> bool:
        """
        Check if the given time falls within this time window, handling overnight windows.
        
        For overnight windows (e.g., 22:00-06:00), this correctly handles the midnight crossing (30-hour clock).
        """
        if not self.is_overnight:
            return self.start_time <= check_time <= self.end_time
        else:
            return check_time >= self.start_time or check_time <= self.end_time
    
    def minutes_from_start(self, check_time: time) -> int:
        """
        Calculate minutes from the start time to the check time, handling overnight windows.
        Returns negative value if check_time is before start_time (for non-overnight windows) (30-hour clock).
        """
        start_minutes = self.start_time.hour * MINUTES_IN_HOUR + self.start_time.minute
        check_minutes = check_time.hour * MINUTES_IN_HOUR + check_time.minute
        
        if not self.is_overnight:
            return check_minutes - start_minutes
        else:
            if check_time >= self.start_time:
                return check_minutes - start_minutes
            else:
                return (check_minutes + MINUTES_IN_DAY) - start_minutes
    
    def minutes_to_end(self, check_time: time) -> int:
        """
        Calculate minutes from the check time to the end time, handling overnight windows.
        Returns negative value if check_time is after end_time (for non-overnight windows) (30-hour clock).
        """
        end_minutes = self.end_time.hour * MINUTES_IN_HOUR + self.end_time.minute
        check_minutes = check_time.hour * MINUTES_IN_HOUR + check_time.minute
        
        if not self.is_overnight:
            return end_minutes - check_minutes
        else:
            if check_time <= self.end_time:
                return end_minutes - check_minutes
            else:
                return (end_minutes + MINUTES_IN_DAY) - check_minutes
    
    def format_time_range(self) -> str:
        """Format the time window as a readable string (30-hour clock)"""
        start_str = self.start_time.strftime("%H:%M")
        end_str = self.end_time.strftime("%H:%M")
        overnight_indicator = " (overnight)" if self.is_overnight else ""
        return f"{start_str}-{end_str}{overnight_indicator}"


class ShiftDefinition(BaseModel):
    """
    Dynamic definition of a shift type, replacing the hardcoded ShiftType enum (30-hour clock).
    
    This allows for creating custom shift types with specific time windows and rules.
    """
    shift_code: str
    shift_name: str

    check_in_window: TimeWindow
    check_out_window: TimeWindow
    
    scheduled_start: time
    scheduled_end: time
    
    is_overnight: bool = False
    
    display_names: Dict[str, str]
    
    overtime_eligible: bool = True
    overtime_start_time: Optional[time] = None
    
    min_duration_minutes: int = 0
    max_duration_minutes: Optional[int] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @model_validator(mode="after")
    def validate_time_windows(self) -> "ShiftDefinition":
        """Ensure time windows are consistent with is_overnight flag (30-hour clock)"""
        if self.is_overnight:
            if not (self.check_in_window.is_overnight or self.check_out_window.is_overnight):
                self.check_in_window.is_overnight = True
                self.check_out_window.is_overnight = True
        
        if self.overtime_eligible and not self.overtime_start_time:
            self.overtime_start_time = self.scheduled_end
        
        return self
    
    def get_display_name(self, language: str = "en") -> str:
        """Get the display name in the specified language, falling back to name if not available (30-hour clock)"""
        return self.display_names.get(language, self.name)


class OvertimeRule(BaseModel):
    start_time: time
    brackets: List[Dict[str, Any]] = Field(default_factory=list)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @classmethod
    def create_standard(cls) -> "OvertimeRule":
        """
        Create the standard overtime rule with 30-minute brackets (30-hour clock).
        
        Standard overtime starts at 17:15 and increases by 0.5 hours for each 30-minute bracket.
        """
        brackets = []
        base_hour = 17
        base_minute = 15
        
        for i in range(14):  # 14 half-hour periods from 17:15 to 00:15 (30-hour clock) 
            hour = base_hour + (base_minute + i * 30) // 60
            minute = (base_minute + i * 30) % 60
            
            if hour >= 24:
                hour -= 24
            
            end_hour = base_hour + (base_minute + (i + 1) * 30) // 60
            end_minute = (base_minute + (i + 1) * 30) % 60
            
            if end_hour >= 24:
                end_hour -= 24
            
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
        """
        Calculate overtime hours based on checkout time.
        
        Returns 0 if checkout is before overtime start time.
        """
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


class ShiftRule(BaseModel):
    shift_code: str
    shift_name: str
    description: str
    
    check_in_window: TimeWindow
    check_out_window: Optional[TimeWindow] = None
    
    shift_type: str
    
    priority: int = 0
    
    error_message: str

    success_message: str
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def matches_check_in(self, check_in_time: time) -> bool:
        return self.check_in_window.contains_time(check_in_time)
    
    def matches_check_out(self, check_out_time: time) -> bool:
        if self.check_out_window is None:
            return True
        return self.check_out_window.contains_time(check_out_time)
    
    def matches(self, check_in_time: time, check_out_time: Optional[time] = None) -> bool:
        if not self.matches_check_in(check_in_time):
            return False
        
        if check_out_time is not None and not self.matches_check_out(check_out_time):
            return False
        
        return True


class ShiftRuleEngine(BaseModel):
    """
    Engine for evaluating shift rules to classify shifts and validate check-in/out times.
    
    This replaces the hardcoded ShiftRule class.
    """
    rules: List[ShiftRule] = Field(default_factory=list)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def add_rule(self, rule: ShiftRule) -> None:
        """Add a business rule to the engine"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def classify_shift(
        self, check_in_time: datetime, check_out_time: Optional[datetime] = None
    ) -> Tuple[Optional[str], str]:
        """
        Classify a shift based on check-in and check-out times.
        
        Returns a tuple of (shift_type, explanation) where shift_type is the code of the
        matching shift type, or None if no rule matches.
        """
        check_in_time_obj = check_in_time.time()
        check_out_time_obj = check_out_time.time() if check_out_time else None
        
        logging.info(
            f"🔍 ShiftRuleEngine.classify_shift - Check-in: {check_in_time_obj}, Check-out: {check_out_time_obj}"
        )
        
        # Try to find a matching rule
        for rule in self.rules:
            if rule.matches(check_in_time_obj, check_out_time_obj):
                message = rule.success_message or f"Matched rule: {rule.shift_name}"
                logging.info(f"✅ Rule matched: {rule.shift_code} - {rule.shift_name}")
                return rule.shift_type, message
        
        # No rule matched
        logging.info("❌ No rule matched")
        return None, f"No matching rule found for check-in: {check_in_time_obj}, check-out: {check_out_time_obj}"
    
    @classmethod
    def create_standard(cls) -> "ShiftRuleEngine":
        """
        Create a standard rule engine with the default shift rules.
        
        This implements the standard rules:
        1. Morning: check in 06:30am–11:59am AND check out before 14:59pm
        2. Afternoon: check in 12:00pm–16:59pm, check out limit is before 29:00pm (5:00am next day)
        3. Full day: check in 06:30am–11:59am AND NO checkout before 15:00pm, check out limit is before 29:00pm
        4. Overnight: check in 17:00pm–05:00am AND checkout before 05:00am next day
        5. No check in after 5:01am with checkout before 06:30am
        """
        engine = cls()
        
        # Rule 1: Morning shift
        engine.add_rule(ShiftRule(
            shift_code="morning_shift",
            shift_name="Morning Shift",
            description="Check in 06:30am–11:59am AND check out before 14:59pm",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(6, 30, 14, 59, display_name="06:30-14:59"),
            shift_type="morning",
            priority=10,
            success_message="早更: 時間範圍內完成",
            error_message="無效嘅早更: 簽退時間不在有效範圍"
        ))
        
        # Rule 2: Afternoon shift
        engine.add_rule(ShiftRule(
            shift_code="afternoon_shift",
            shift_name="Afternoon Shift",
            description="Check in 12:00pm–16:59pm, check out limit is before 29:00pm (5:00am next day)",
            check_in_window=TimeWindow.create(12, 0, 16, 59, display_name="12:00-16:59"),
            check_out_window=TimeWindow.create(12, 0, 5, 0, is_overnight=True, display_name="12:00-05:00 (next day)"),
            shift_type="afternoon",
            priority=10,
            success_message="午更: 時間正確",
            error_message="無效嘅午更: 簽退太遲"
        ))
        
        # Rule 3: Full day shift 1
        engine.add_rule(ShiftRule(
            shift_code="full_day_shift_1",
            shift_name="Full Day Shift 1",
            description="Check in 06:30am–11:59am AND checkout after 15:00pm, before 29:00pm",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(15, 0, 5, 0, is_overnight=True, display_name="15:00-05:00 (next day)"),
            shift_type="Shift 1",
            priority=20,  # Higher priority than morning shift
            success_message="全日更1: 工作超過14:59",
            error_message="無效嘅全日更1: 簽退時間不在有效範圍"
        ))
        
        # Rule 4: Overnight shift
        engine.add_rule(ShiftRule(
            shift_code="overnight_shift",
            shift_name="Overnight Shift",
            description="Check in 17:00pm–05:00am AND checkout before 05:00am next day",
            check_in_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, display_name="17:00-05:00"),
            check_out_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, display_name="17:00-05:00 (next day)"),
            shift_type="overnight",
            priority=10,
            success_message="夜更: 時間正確",
            error_message="無效嘅夜更: 簽退太遲"
        ))
        
        # Rule 5: Invalid early morning check-in/out (error case)
        engine.add_rule(ShiftRule(
            shift_code="invalid_early_morning",
            shift_name="Invalid Early Morning",
            description="No check in after 5:01am with checkout before 06:30am",
            check_in_window=TimeWindow.create(5, 1, 6, 29, display_name="05:01-06:29"),
            check_out_window=TimeWindow.create(5, 1, 6, 29, display_name="05:01-06:29"),
            shift_type=None,
            priority=100,  # Highest priority to catch this error case first
            success_message="",  # Should never succeed
            error_message="錯誤: 05:01後簽到但06:30前簽退係無效嘅"
        ))
        
        return engine


class ShiftConfiguration(Document):
    project_id: str = Field(..., index=True)

    shift_definitions: List[ShiftDefinition] = Field(default_factory=list)
    shift_rules: List[ShiftRule] = Field(default_factory=list)
    overtime_rules: Dict[str, OvertimeRule] = Field(default_factory=dict)
    allow_multiple_shifts: bool = True
    max_shifts_per_day: int = 3
    
    use_standard_shifts_as_fallback: bool = True
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    deleted_at: Optional[datetime] = None
    
    class Settings:
        name = "shift_configuration_collection"
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def get_rule_engine(self) -> ShiftRuleEngine:
        """Get a rule engine initialized with this project's business rules"""
        engine = ShiftRuleEngine()
        for rule in self.shift_rules:
            engine.add_rule(rule)
        return engine
    
    def get_shift_definition(self, shift_type: str) -> Optional[ShiftDefinition]:
        """Get a shift definition by its code"""
        for definition in self.shift_definitions:
            if definition.shift_code == shift_type:
                return definition
        return None
    
    def get_overtime_rule(self, shift_type: str) -> Optional[OvertimeRule]:
        """Get the overtime rule for a specific shift type"""
        return self.overtime_rules.get(shift_type)
    

    @classmethod
    async def get_for_project(cls, project_id: str) -> Optional["ShiftConfiguration"]:
        """Get the shift configuration for a specific project"""
        config = await cls.find_one(cls.project_id == project_id, cls.deleted_at == None)
        return config
    
    @classmethod
    async def get_or_create_standard(cls, project_id: str) -> "ShiftConfiguration":
        """Get the shift configuration for a project or create a standard one if it doesn't exist"""
        config = await cls.get_for_project(project_id)
        if config:
            return config
        
        standard_config = cls.create_standard(project_id)
        await standard_config.insert()
        return standard_config
    
    @classmethod
    def create_standard(cls, project_id: str) -> "ShiftConfiguration":
        """Create a standard shift configuration with default settings"""
        morning_shift = ShiftDefinition(
            shift_code="morning",
            shift_name="Morning Shift",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(6, 30, 14, 59, display_name="06:30-14:59"),
            scheduled_start=time(8, 0),
            scheduled_end=time(12, 0),
            is_overnight=False,
            display_names={"en": "Morning Shift", "zh-hk": "早更"}
        )
        
        afternoon_shift = ShiftDefinition(
            shift_code="afternoon",
            shift_name="Afternoon Shift",
            check_in_window=TimeWindow.create(12, 0, 16, 59, display_name="12:00-16:59"),
            check_out_window=TimeWindow.create(12, 0, 5, 0, is_overnight=True, display_name="12:00-05:00 (next day)"),
            scheduled_start=time(13, 0),
            scheduled_end=time(17, 0),
            is_overnight=False,
            display_names={"en": "Afternoon Shift", "zh-hk": "午更"}
        )
        
        full_day_shift = ShiftDefinition(
            shift_code="full_day",
            shift_name="Full Day Shift",
            check_in_window=TimeWindow.create(6, 30, 11, 59, display_name="06:30-11:59"),
            check_out_window=TimeWindow.create(15, 0, 5, 0, is_overnight=True, display_name="15:00-05:00 (next day)"),
            scheduled_start=time(8, 0),
            scheduled_end=time(17, 0),
            is_overnight=False,
            display_names={"en": "Full Day Shift"}
        )
        
        overnight_shift = ShiftDefinition(
            shift_code="overnight",
            shift_name="Overnight Shift",
            check_in_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, display_name="17:00-05:00"),
            check_out_window=TimeWindow.create(17, 0, 5, 0, is_overnight=True, display_name="17:00-05:00 (next day)"),
            scheduled_start=time(17, 15),
            scheduled_end=time(0, 15),
            is_overnight=True,
            display_names={"en": "Overnight Shift", "zh-hk": "夜更"}
        )
        
        rule_engine = ShiftRuleEngine.create_standard()
        standard_ot_rule = OvertimeRule.create_standard()
        
        return cls(
            project_id=project_id,
            shift_definitions=[morning_shift, afternoon_shift, full_day_shift, overnight_shift],
            shift_rules=rule_engine.rules,
            overtime_rules={
                "morning": None,
                "afternoon": standard_ot_rule,
                "full_day": standard_ot_rule,
                "overnight": standard_ot_rule
            },
            allow_multiple_shifts=True,
            max_shifts_per_day=3,
            use_standard_shifts_as_fallback=True
        )
