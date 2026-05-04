from __future__ import annotations
import asyncio
import decimal
import logging
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple 
from src.models.user_model import WorkingHours
from beanie import Document
from bson import ObjectId
from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_validator, model_validator)

from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day, HK_TZ
from src.models.project_model import Project
from src.models.user_model import User

base_url = os.getenv("BASE_URL")


def convert_mongodb_decimal_to_string(value) -> str:

    if value is None:
        return ""

    try:
        if hasattr(value, "to_decimal"):
            return str(value.to_decimal())
        elif hasattr(value, "__float__"):
            return str(float(value))
        else:
            return str(value)
    except (ValueError, TypeError):
        return str(value)


class AttendanceStatus(str, Enum):
    """Enhanced attendance status types with more granular states"""

    NO_RECORD = "no_record"
    CHECKED_IN_PENDING = "checked_in_pending"  # Has check-in, awaiting check-out
    SHIFT_COMPLETED = "shift_completed"  # Single shift complete
    PARTIAL_DAY = "partial_day"  # Some shifts complete, others pending
    FULL_DAY_COMPLETED = "full_day_completed"  # All planned shifts complete
    ANOMALOUS_ACTIVITY = "anomalous_activity"  # Too many check-ins/outs
    INCOMPLETE_SHIFT = "incomplete_shift"  # Shift started but never completed
    ERROR = "error"  # System error occurred


class ShiftType(str, Enum):
    FULL_DAY_1 = "Shift 1"
    FULL_DAY_2 = "Shift 2"
    FULL_DAY_3 = "Shift 3"
    FULL_DAY_4 = "Shift 4"

class CheckType(str, Enum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"


class ShiftClassificationRules:
    """Enhanced shift classification with proper time-based logic for multiple shifts"""

    @staticmethod
    def classify_shift(
        checkin_time: datetime, 
        checkout_time: Optional[datetime] = None,
        existing_shifts: Optional[List['ShiftAttendance']] = None
    ) -> Tuple[Optional[ShiftType], str]:

        checkin_time_obj = checkin_time.astimezone(HK_TZ).time()
        checkout_time_obj = checkout_time.astimezone(HK_TZ).time() if checkout_time else None

        logging.info(
            f"🔍 ShiftClassificationRules.classify_shift - Check-in: {checkin_time_obj}, Check-out: {checkout_time_obj}"
        )

        # All shifts use the same flexible time window (00:00-23:59)
        flexible_window = {
            'check_in': (0 * 60, 23 * 60 + 59),  # 00:00-23:59
            'check_out': (0 * 60, 23 * 60 + 59),  # 00:00-23:59
            'description': 'Flexible working hours'
        }
        
        shift_windows = {
            ShiftType.FULL_DAY_1: flexible_window,
            ShiftType.FULL_DAY_2: flexible_window,
            ShiftType.FULL_DAY_3: flexible_window,
            ShiftType.FULL_DAY_4: flexible_window
        }

        checkin_minutes = checkin_time_obj.hour * 60 + checkin_time_obj.minute
        checkout_minutes = checkout_time_obj.hour * 60 + checkout_time_obj.minute if checkout_time_obj else None

        logging.info(f"🔍 Check-in minutes: {checkin_minutes}, Check-out minutes: {checkout_minutes}")

        # All shifts use flexible hours (00:00-23:59), so any valid time is accepted
        # The actual shift assignment will be determined by sequential consumption logic
        check_in_min, check_in_max = flexible_window['check_in']
        
        # Validate check-in time is within flexible window
        if not (check_in_min <= checkin_minutes <= check_in_max):
            return None, f"Invalid check-in time: {checkin_time_obj} (must be between 00:00-23:59)"
        
        # Determine the next available shift based on existing shifts
        if existing_shifts:
            # Get completed shifts (shifts that have both check-in and check-out)
            completed_shifts = set()
            for shift in existing_shifts:
                if shift.effective_check_in and shift.effective_check_out:
                    completed_shifts.add(shift.shift_type)
            
            # Get the next available shift
            next_shift = ShiftClassificationRules.get_next_available_shift(completed_shifts)
            if next_shift:
                return next_shift, f"Valid flexible check-in time: {checkin_time_obj} (Next available shift: {next_shift.value})"
            else:
                return None, "All shifts have been completed for this day"
        
        # If no existing shifts, return the first shift
        if checkout_minutes is None:
            return ShiftType.FULL_DAY_1, f"Valid flexible check-in time: {checkin_time_obj}"
        
        # With checkout time, validate it's within flexible window
        check_out_min, check_out_max = flexible_window['check_out']
        if not (check_out_min <= checkout_minutes <= check_out_max):
            return None, f"Invalid check-out time: {checkout_time_obj} (must be between 00:00-23:59)"
        
        # Return the first available shift (actual assignment handled by sequential consumption)
        return ShiftType.FULL_DAY_1, f"Valid flexible shift: {flexible_window['description']}"

    @staticmethod
    def get_next_available_shift(completed_shifts: set) -> Optional[ShiftType]:
        """
        Get the next available shift in sequential order.
        Returns the next shift that hasn't been completed yet.
        """
        shift_order = [ShiftType.FULL_DAY_1, ShiftType.FULL_DAY_2, ShiftType.FULL_DAY_3, ShiftType.FULL_DAY_4]
        
        for shift_type in shift_order:
            if shift_type not in completed_shifts:
                return shift_type
        
        return None  # All shifts completed


class ShiftConfiguration(BaseModel):
    """Enhanced configuration for each shift type with comprehensive business rules"""
    shift_type: ShiftType
    scheduled_start: time
    scheduled_end: time

    @classmethod
    def get_configurations(cls, user_working_hours: Optional[List['WorkingHours']] = None) -> Dict[ShiftType, 'ShiftConfiguration']:
        """Get shift configurations with specific time windows for each shift type"""
        
        # All shifts use flexible hours (00:00-23:59)
        flexible_hours = {
            'start': time(0, 0),   # 00:00
            'end': time(23, 59)    # 23:59
        }
        
        shift_defaults = {
            ShiftType.FULL_DAY_1: flexible_hours,
            ShiftType.FULL_DAY_2: flexible_hours,
            ShiftType.FULL_DAY_3: flexible_hours,
            ShiftType.FULL_DAY_4: flexible_hours
        }

        # All shifts use the same flexible hours regardless of user working hours
        # User working hours are noted for logging but don't affect shift configuration
        if user_working_hours and len(user_working_hours) > 0:
            try:
                working_hours = user_working_hours[0]
                logging.info(f"User working hours: {working_hours.start_time}-{working_hours.end_time}, but all shifts use flexible 00:00-23:59")
            except (ValueError, AttributeError) as e:
                logging.warning(f"Invalid working hours format: {e}. Using flexible shift configurations.")
        
        # Create configurations for all shift types
        configurations = {}
        for shift_type, times in shift_defaults.items():
            configurations[shift_type] = cls(
                shift_type=shift_type,
                scheduled_start=times['start'],
                scheduled_end=times['end']
            )
        
        return configurations   

class CheckInOutRecord(BaseModel):
    check_type: CheckType
    attendance_method: bool = Field(default=True)  # True for GPS, False for Image
    image_file_ids: Optional[List[str]] = Field(
        default=None
    )  # Optional image file id when attendance method is False (image upload)
    latitude: str  # String representation of decimal latitude
    longitude: str  # String representation of decimal longitude
    accuracy: str  # String representation of decimal accuracy in meters
    timestamp: datetime  # Stored in Hong Kong timezone

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    @field_validator("latitude", "longitude", "accuracy", mode="before")
    @classmethod
    def convert_mongodb_types(cls, v):
        """Convert MongoDB types to string before validation"""
        return convert_mongodb_decimal_to_string(v)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_reasonable(cls, v: datetime) -> datetime:
        """Ensure timestamp is within reasonable bounds"""
        if v.year < 2020 or v.year > 2030:
            raise ValueError(f"Timestamp year {v.year} is outside reasonable range")
        return v

    @field_validator("accuracy")
    @classmethod
    def validate_accuracy(cls, v: str) -> str:
        """Validate accuracy can be converted to positive Decimal and return as string"""
        try:
            # Convert MongoDB types to string first
            v = convert_mongodb_decimal_to_string(v)

            # Check for invalid string values before conversion
            if not v or v.lower() in [
                "nan",
                "inf",
                "-inf",
                "infinity",
                "-infinity",
                "none",
                "null",
            ]:
                return "0"

            # Try to convert to float first to catch invalid strings
            try:
                float_val = float(v)
                if float_val < 0 or str(float_val).lower() in ["nan", "inf", "-inf"]:
                    return "0"
            except (ValueError, TypeError):
                return "0"

            # Now safely convert to Decimal
            acc_val = Decimal(v)
            if acc_val < Decimal(0):
                return "0"

            # Always return as string for consistency
            return str(acc_val)
        except (
            ValueError,
            TypeError,
            decimal.InvalidOperation,
            decimal.ConversionSyntax,
        ):
            # Fallback for invalid/empty values to keep record load robust
            return "0"

    @model_validator(mode="after")
    def validate_attendance_method_image_file_ids_relationship(self):
        """Validate that attendance_method and image_file_ids are consistent"""
        if self.attendance_method and self.image_file_ids is not None:
            raise ValueError(
                "When attendance_method is True (GPS), image_file_ids must be None"
            )
        if not self.attendance_method and self.image_file_ids is None:
            raise ValueError(
                "When attendance_method is False (Image), image_file_ids must not be None"
            )
        return self

    @property
    def location_url(self) -> str:
        """Generate Google Maps URL for this location"""
        return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"

    
    async def validate_for_shift_type(self, shift_type: ShiftType) -> Tuple[bool, str]:
        """Validate this record against a specific shift type"""
        record_time = self.timestamp.astimezone(HK_TZ).time()
        record_minutes = record_time.hour * 60 + record_time.minute
        
        # Pre-calculated time windows for better performance
        """Classify check-in & check-out shift Rules:
        1. Full day_1: check in 00:00am, check out limit is before 23:59pm

        """
        time_windows = {
            (CheckType.CHECK_IN, ShiftType.FULL_DAY_1): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_IN, ShiftType.FULL_DAY_2): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_IN, ShiftType.FULL_DAY_3): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_IN, ShiftType.FULL_DAY_4): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_OUT, ShiftType.FULL_DAY_1): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_OUT, ShiftType.FULL_DAY_2): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_OUT, ShiftType.FULL_DAY_3): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
            (CheckType.CHECK_OUT, ShiftType.FULL_DAY_4): (0*60, 23*60+59, "0:00 AM - 23:59 AM"),
        }
        
        window_key = (self.check_type, shift_type)
        

        if window_key not in time_windows:
            return False, f"未知嘅更次/檢查類型組合: {self.check_type.value}/{shift_type.value}"
        
        earliest, latest, window_desc = time_windows[window_key]
        
        if not (earliest <= record_minutes <= latest):
            action = "check-in" if self.check_type == CheckType.CHECK_IN else "check-out"
            return False, f"{shift_type.value.title()}更次 {action} 時間 {record_time} 超出允許範圍 ({window_desc})"
        
        return True, "有效"
    


class ShiftAttendance(BaseModel):

    shift_type: ShiftType = Field(default=ShiftType.FULL_DAY_1)
    check_in_out_records: List[CheckInOutRecord] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    @field_validator("check_in_out_records", mode="before")
    @classmethod
    def preprocess_records(cls, v: List[Any]) -> List[Any]:
        """Pre-process MongoDB types in records before validation"""
        if isinstance(v, list):
            for record in v:
                if isinstance(record, dict):
                    # Convert Decimal128 fields to strings
                    for field in ["latitude", "longitude", "accuracy"]:
                        if field in record and record[field] is not None:
                            record[field] = convert_mongodb_decimal_to_string(
                                record[field]
                            )
        return v

    @field_validator("check_in_out_records")
    @classmethod
    def validate_records(cls, v: List[CheckInOutRecord]) -> List[CheckInOutRecord]:
        """Validate check-in/out records constraints - allow multiple cycles"""
        # Remove the 2-record limit to allow multiple check-in/check-out cycles
        # if len(v) > 2:
        #     raise ValueError("一個更次最多可以有2個簽到/簽退記錄")

        # Validate that records are properly paired (no consecutive same types)
        for i in range(len(v) - 1):
            current_record = v[i]
            next_record = v[i + 1]
            
            # Prevent consecutive records of the same type
            if current_record.check_type == next_record.check_type:
                raise ValueError(f"不能連續{current_record.check_type.value}，請先{CheckType.CHECK_OUT.value if current_record.check_type == CheckType.CHECK_IN else CheckType.CHECK_IN.value}")

        # Validate that check-out records have corresponding check-in records
        checkin_count = sum(1 for r in v if r.check_type == CheckType.CHECK_IN)
        checkout_count = sum(1 for r in v if r.check_type == CheckType.CHECK_OUT)
        
        # Allow multiple cycles but ensure proper pairing
        if checkout_count > checkin_count:
            raise ValueError("簽退記錄不能多於簽到記錄")

        return v


    # Computed fields based on records
    @computed_field
    @property
    def effective_check_in(self) -> Optional[datetime]:
        """First valid check-in for this shift"""
        checkin_records = [
            r for r in self.check_in_out_records if r.check_type == CheckType.CHECK_IN
        ]
        if not checkin_records:
            return None
        return min(record.timestamp for record in checkin_records)

    @computed_field
    @property
    def effective_check_out(self) -> Optional[datetime]:
        """Last valid check-out for this shift"""
        checkout_records = [
            r for r in self.check_in_out_records if r.check_type == CheckType.CHECK_OUT
        ]
        if not checkout_records:
            return None
        return max(record.timestamp for record in checkout_records)

    @computed_field
    @property
    def shift_configuration(self) -> ShiftConfiguration:
        """Get the configuration for this shift type"""
        try:
            config = ShiftConfiguration.get_configurations().get(self.shift_type)
            if config is None:
                logging.warning(f"No configuration found for shift type {self.shift_type}, using FULL_DAY_1 as fallback")
                config = ShiftConfiguration.get_configurations()[ShiftType.FULL_DAY_1]
            return config
        except (KeyError, TypeError, AttributeError) as e:
            logging.error(f"Error getting shift configuration for {self.shift_type}: {e}, using default")
            # Return full day shift configuration as fallback
            return ShiftConfiguration.get_configurations()[ShiftType.FULL_DAY_1]
    
    
    async def get_shift_configuration_with_user_hours(self, worker_id: str) -> ShiftConfiguration:
        """Get the configuration for this shift type with user's working hours"""
        try:
            user = await User.find_one(
                User.id == ObjectId(worker_id),
                User.deleted_at == None
            )
            
            user_working_hours = None
            if user and user.working_hours:
                user_working_hours = user.working_hours
            
            configs = ShiftConfiguration.get_configurations(user_working_hours)
            config = configs.get(self.shift_type)
            
            if config is None:
                logging.warning(f"No configuration found for shift type {self.shift_type}, using FULL_DAY_1  as fallback")
                config = configs[ShiftType.FULL_DAY_1]
            
            return config
        except Exception as e:
            logging.error(f"Error getting shift configuration with user hours for {self.shift_type}: {e}, using default")
            # Return default configuration as fallback
            return ShiftConfiguration.get_configurations()[ShiftType.FULL_DAY_1]
    

    @computed_field
    @property
    def is_complete(self) -> bool:
        """Whether this shift has both check-in and check-out"""
        try:
            return (
                self.effective_check_in is not None
                and self.effective_check_out is not None
            )
        except Exception as e:
            logging.error(f"Error checking if shift is complete: {e}, returning False")
            return False

    @computed_field
    @property
    def is_late_check_in(self) -> bool:
        """Enhanced late check-in detection with proper timezone handling"""
        try:
            if not self.effective_check_in:
                return False

            config = self.shift_configuration
            checkin_date = self.effective_check_in.date()

            # Handle overnight shifts that may start previous day
            if self.shift_type == ShiftType.FULL_DAY_1 or self.shift_type == ShiftType.FULL_DAY_2 or self.shift_type == ShiftType.FULL_DAY_3 or self.shift_type == ShiftType.FULL_DAY_4:
                checkin_time = self.effective_check_in.time()
                checkin_minutes = checkin_time.hour * 60 + checkin_time.minute

                if checkin_minutes <= 15:
                    scheduled_start_dt = datetime.combine(
                        checkin_date - timedelta(days=1), config.scheduled_start
                    ).astimezone(HK_TZ)
                else:
                    scheduled_start_dt = datetime.combine(
                        checkin_date, config.scheduled_start
                    ).astimezone(HK_TZ)
            else:
                scheduled_start_dt = datetime.combine(
                    checkin_date, config.scheduled_start
                ).astimezone(HK_TZ)

            grace_period_dt = scheduled_start_dt + timedelta(minutes=1)

            # Make effective_check_in timezone-aware for comparison
            effective_check_in_aware = self.effective_check_in.replace(tzinfo=HK_TZ)
            return effective_check_in_aware > grace_period_dt

        except Exception as e:
            logging.error(f"Error calculating is_late_check_in: {e}, returning False")
            return False


    @computed_field
    @property
    def is_early_check_out(self) -> bool:
        """Enhanced early checkout detection with improved overnight handling"""
        try:
            if not self.effective_check_out:
                return False

            config = self.shift_configuration
            checkout_date = self.effective_check_out.date()
            checkout_time = self.effective_check_out.time()
            checkout_minutes = checkout_time.hour * 60 + checkout_time.minute

            # Enhanced overnight shift handling
            if self.shift_type == ShiftType.FULL_DAY_1 or self.shift_type == ShiftType.FULL_DAY_2 or self.shift_type == ShiftType.FULL_DAY_3 or self.shift_type == ShiftType.FULL_DAY_4:
                if checkout_minutes <= 15: 
                    scheduled_end_dt = datetime.combine(
                        checkout_date, config.scheduled_end
                    ).replace(tzinfo=HK_TZ)
                else:
                    scheduled_end_dt = datetime.combine(
                        checkout_date + timedelta(days=1), config.scheduled_end
                    ).replace(tzinfo=HK_TZ)
            else:
                scheduled_end_dt = datetime.combine(
                    checkout_date, config.scheduled_end
                ).replace(tzinfo=HK_TZ)

            # Make effective_check_out timezone-aware for comparison
            effective_check_out_aware = self.effective_check_out.replace(tzinfo=HK_TZ)
            return effective_check_out_aware < scheduled_end_dt

        except Exception as e:
            logging.error(f"Error calculating is_early_check_out: {e}, returning False")
            return False

    @computed_field
    @property
    def early_minutes(self) -> int:
        """Enhanced early minutes calculation matching improved checkout logic"""
        try:
            if not self.is_early_check_out or not self.effective_check_out:
                return 0

            config = self.shift_configuration
            checkout_date = self.effective_check_out.date()
            checkout_time = self.effective_check_out.time()
            checkout_minutes = checkout_time.hour * 60 + checkout_time.minute

            # Use same logic as is_early_check_out for consistenc
            if self.shift_type == ShiftType.FULL_DAY_1 or self.shift_type == ShiftType.FULL_DAY_2 or self.shift_type == ShiftType.FULL_DAY_3 or self.shift_type == ShiftType.FULL_DAY_4:
                if checkout_minutes <= 15:  # After midnight
                    scheduled_end_dt = datetime.combine(
                        checkout_date, config.scheduled_end
                    ).replace(tzinfo=HK_TZ)
                else:
                    scheduled_end_dt = datetime.combine(
                        checkout_date + timedelta(days=1), config.scheduled_end
                    ).replace(tzinfo=HK_TZ)
            else:
                scheduled_end_dt = datetime.combine(
                    checkout_date, config.scheduled_end
                ).replace(tzinfo=HK_TZ)  

            # Make effective_check_out timezone-aware for comparison (same as is_early_check_out)
            if self.effective_check_out.tzinfo is None:
                effective_check_out_aware = self.effective_check_out.replace(tzinfo=HK_TZ)
            else:
                effective_check_out_aware = self.effective_check_out.astimezone(HK_TZ)

            return max(
                0,
                int((scheduled_end_dt - effective_check_out_aware).total_seconds() / 60),
            )

        except Exception as e:
            logging.error(f"Error calculating early_minutes: {e}, returning 0")
            return 0

    @property
    def ot_hours(self) -> Decimal:
        """Calculate overtime hours using enhanced logic for all shift types"""
        try:
            if not self.effective_check_out or not self.is_complete:
                return Decimal(0)

            checkout_time = self.effective_check_out.astimezone(HK_TZ).time()

            if self.shift_type == ShiftType.FULL_DAY_1 or self.shift_type == ShiftType.FULL_DAY_2 or self.shift_type == ShiftType.FULL_DAY_3 or self.shift_type == ShiftType.FULL_DAY_4:
                return self._calculate_ot_hours(checkout_time)

            # Only calculate OT if they worked past the scheduled end time
            config = self.shift_configuration
            scheduled_end_minutes = config.scheduled_end.hour * 60 + config.scheduled_end.minute
            checkout_minutes = checkout_time.hour * 60 + checkout_time.minute

            # Must work past scheduled time to get OT
            if checkout_minutes <= scheduled_end_minutes:
                return Decimal(0)

            return self._calculate_ot_hours(checkout_time)

        except (
            ValueError,
            TypeError,
            decimal.InvalidOperation,
            decimal.ConversionSyntax,
        ) as e:
            logging.error(f"Error calculating OT hours: {e}, returning 0")
            return Decimal(0)

    @computed_field
    @property
    def shift_status(self) -> str:
        """Human-readable shift status"""
        if not self.effective_check_in:
            return "未開始"
        elif self.is_complete:
            return "已完成"
        else:
            return "進行中"

    def _calculate_ot_hours(self, checkout_time: time) -> Decimal:
        """Calculate OT hours based on the provided table"""
        try:
            hour = checkout_time.hour
            minute = checkout_time.minute

            # OT only starts after 17:15 (5:15 PM)
            if hour < 17 or (hour == 17 and minute < 16):
                return Decimal(0)
            elif hour == 17 and 16 <= minute <= 45:
                return Decimal(0.5)
            elif (hour == 17 and minute >= 46) or (hour == 18 and minute <= 15):
                return Decimal(1)
            elif hour == 18 and 16 <= minute <= 45:
                return Decimal(1.5)
            elif (hour == 18 and minute >= 46) or (hour == 19 and minute <= 15):
                return Decimal(2)
            elif hour == 19 and 16 <= minute <= 45:
                return Decimal(2.5)
            elif (hour == 19 and minute >= 46) or (hour == 20 and minute <= 15):
                return Decimal(3)
            elif hour == 20 and 16 <= minute <= 45:
                return Decimal(3.5)
            elif (hour == 20 and minute >= 46) or (hour == 21 and minute <= 15):
                return Decimal(4)
            elif hour == 21 and 16 <= minute <= 45:
                return Decimal(4.5)
            elif (hour == 21 and minute >= 46) or (hour == 22 and minute <= 15):
                return Decimal(5)
            elif hour == 22 and 16 <= minute <= 45:
                return Decimal(5.5)
            elif (hour == 22 and minute >= 46) or (hour == 23 and minute <= 15):
                return Decimal(6)
            elif hour == 23 and 16 <= minute <= 45:
                return Decimal(6.5)
            elif (hour == 23 and minute >= 46) or (hour == 0 and minute <= 15):
                return Decimal(7)
            else:
                return Decimal(7)  # Max OT hours
        except (
            ValueError,
            TypeError,
            decimal.InvalidOperation,
            decimal.ConversionSyntax,
        ) as e:
            logging.error(
                f"Error calculating OT hours from checkout time: {e}, returning 0"
            )
            return Decimal(0)

    async def add_check_in_out_record(self, record: CheckInOutRecord) -> Tuple[bool, str]:
        """Add a check-in or check-out record with enhanced validation"""

        is_valid, message = await record.validate_for_shift_type(shift_type=self.shift_type)
        if not is_valid:
            return False, message

        # Enhanced validation for multiple check-in/check-out cycles
        if record.check_type == CheckType.CHECK_IN:
            # For check-in, only prevent if there's already a check-in without a corresponding check-out
            # This allows multiple check-in/check-out cycles within the same shift
            recent_checkin = None
            recent_checkout = None
            
            # Find the most recent check-in and check-out
            for r in reversed(self.check_in_out_records):
                if r.check_type == CheckType.CHECK_IN and recent_checkin is None:
                    recent_checkin = r
                elif r.check_type == CheckType.CHECK_OUT and recent_checkout is None:
                    recent_checkout = r
                    
            # Only prevent check-in if there's an unpaired check-in (no corresponding check-out)
            if recent_checkin and not recent_checkout:
                return False, f"You have already checked in for this shift. Please check out first."
                
        elif record.check_type == CheckType.CHECK_OUT:
            # For check-out, ensure there's a recent check-in without a corresponding check-out
            recent_checkin = None
            recent_checkout = None
            
            # Find the most recent check-in and check-out
            for r in reversed(self.check_in_out_records):
                if r.check_type == CheckType.CHECK_IN and recent_checkin is None:
                    recent_checkin = r
                elif r.check_type == CheckType.CHECK_OUT and recent_checkout is None:
                    recent_checkout = r
                    
            if not recent_checkin:
                return False, "You cannot check out without checking in first"
                
            # Only prevent check-out if there's already a check-out without a new check-in after it
            if recent_checkout and recent_checkout.timestamp > recent_checkin.timestamp:
                return False, "You have already checked out for this shift. Please check in first."
                
            # Validate checkout is after the most recent checkin
            if record.timestamp <= recent_checkin.timestamp:
                return False, "Check-out time must be after check-in time"

        # Add the record
        self.check_in_out_records.append(record)

        # Update computed state efficiently
        if record.check_type == CheckType.CHECK_OUT:
            # Trigger any shift type reclassification if needed
            self._update_shift_classification()

        return True, f"{record.check_type.value.replace('_', '-').title()} successfully added"

    def _update_shift_classification(self) -> None:
        """Update shift type based on actual check-in/out times"""
        if self.effective_check_in and self.effective_check_out:
            # Log current state before classification
            logging.info(
                f"🔄 Updating shift classification - Current: {self.shift_type.value}, Check-in: {self.effective_check_in.time()}, Check-out: {self.effective_check_out.time()}"
            )

            # Use classification rules to determine final shift type
            final_type, explanation = ShiftClassificationRules.classify_shift(
                self.effective_check_in, self.effective_check_out
            )

            logging.info(
                f"📋 Classification result - Final type: {final_type.value if final_type else 'None'}, Explanation: {explanation}"
            )

            if final_type and final_type != self.shift_type:
                logging.info(
                    f"🔄 Shift type changed from {self.shift_type.value} to {final_type.value}"
                )
                self.shift_type = final_type
            else:
                logging.info(f"✅ Shift type unchanged: {self.shift_type.value}")


class AttendanceRecord(Document):
    worker_id: str = Field(..., index=True)  
    project_id: str = Field(..., index=True)  
    attendance_date: date = Field(
        default_factory=get_this_day, index=True
    ) 
    lunch_overtime: Optional[bool] = Field(default=False)

    raw_records: List[CheckInOutRecord] = Field(
        default_factory=list
    )

    shifts: List[ShiftAttendance] = Field(
        default_factory=list
    ) 

    created_at: datetime = Field(default_factory=get_this_moment)
    updated_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    @field_validator("raw_records", mode="before")
    @classmethod
    def preprocess_raw_records(cls, v: List[Any]) -> List[Any]:
        """Pre-process MongoDB types in raw records before validation"""
        if isinstance(v, list):
            for record in v:
                if isinstance(record, dict):
                    # Convert Decimal128 fields to strings
                    for field in ["latitude", "longitude", "accuracy"]:
                        if field in record and record[field] is not None:
                            record[field] = convert_mongodb_decimal_to_string(
                                record[field]
                            )
        return v

    @field_validator("shifts", mode="before")
    @classmethod
    def preprocess_shifts(cls, v: List[Any]) -> List[Any]:
        """Pre-process MongoDB types in shifts before validation"""
        if isinstance(v, list):
            for shift in v:
                if isinstance(shift, dict) and "check_in_out_records" in shift:
                    for record in shift["check_in_out_records"]:
                        if isinstance(record, dict):
                            # Convert Decimal128 fields to strings
                            for field in ["latitude", "longitude", "accuracy"]:
                                if field in record and record[field] is not None:
                                    record[field] = convert_mongodb_decimal_to_string(
                                        record[field]
                                    )
        return v

    # Computed summary fields
    @computed_field
    @property
    def total_ot_hours(self) -> Decimal:  # daily
        """Total OT hours across all shifts"""
        try:
            # Filter out None values and ensure all values are Decimal
            ot_hours_list = []
            for shift in self.shifts:
                try:
                    ot_hours = shift.ot_hours
                    if ot_hours is not None:
                        ot_hours_list.append(ot_hours)
                    else:
                        logging.warning(
                            f"Shift {shift.shift_type.value} returned None ot_hours, skipping"
                        )
                except Exception as e:
                    logging.warning(
                        f"Error getting ot_hours for shift {shift.shift_type.value}: {e}, skipping"
                    )
                    continue

            if not ot_hours_list:
                return Decimal(0)

            return sum(ot_hours_list)
        except (
            ValueError,
            TypeError,
            decimal.InvalidOperation,
            decimal.ConversionSyntax,
        ) as e:
            logging.error(f"Error calculating total OT hours: {e}, returning 0")
            return Decimal(0)

    @computed_field
    @property
    def completed_shifts(self) -> List[ShiftType]:
        """List of completed shift types"""
        return [shift.shift_type for shift in self.shifts if shift.is_complete]

    @computed_field
    @property
    def pending_shifts(self) -> List[ShiftType]:
        """List of shifts with check-in but no check-out"""
        return [
            shift.shift_type
            for shift in self.shifts
            if shift.effective_check_in and not shift.effective_check_out
        ]

    @computed_field
    @property
    def daily_shift_count(self) -> int:
        """Total number of shifts (with any activity)"""
        return len(self.shifts)

    @computed_field
    @property
    def attendance_status(self) -> AttendanceStatus:
        """Overall attendance status for the day"""
        if not self.shifts:
            return AttendanceStatus.NO_RECORD

        completed = len(self.completed_shifts)
        pending = len(self.pending_shifts)
        total = len(self.shifts)

        if pending > 0:
            return AttendanceStatus.CHECKED_IN_PENDING
        elif completed == 1 and total == 1:
            return AttendanceStatus.SHIFT_COMPLETED
        elif completed > 0 and completed < total:
            return AttendanceStatus.PARTIAL_DAY
        elif completed > 0:
            return AttendanceStatus.FULL_DAY_COMPLETED
        else:
            return AttendanceStatus.NO_RECORD

    class Settings:
        name = "attendance_record_collection"

    model_config = ConfigDict(
        arbitrary_types_allowed=True, validate_assignment=True, populate_by_name=True
    )

    @staticmethod
    def validate_shift_transition(
        current_shift: ShiftType, new_checkin: datetime, completed_shifts: set = None
    ) -> Tuple[bool, str]:
        """
        Validate if a new shift can be started after completing the current shift.
        Returns (is_valid, reason)
        """
        if completed_shifts is None:
            completed_shifts = set()
            
        new_minutes = new_checkin.hour * 60 + new_checkin.minute

        # Define minimum rest periods between shifts (in minutes)
        rest_periods = {
            ShiftType.FULL_DAY_1: 60,  # 1 hour rest after shift 1
            ShiftType.FULL_DAY_2: 60,  # 1 hour rest after shift 2
            ShiftType.FULL_DAY_3: 120, # 2 hours rest after overnight shift 3
            ShiftType.FULL_DAY_4: 60   # 1 hour rest after shift 4
        }

        # Check if all shifts are already completed
        all_shifts = {ShiftType.FULL_DAY_1, ShiftType.FULL_DAY_2, ShiftType.FULL_DAY_3, ShiftType.FULL_DAY_4}
        if completed_shifts.issuperset(all_shifts):
            return False, "所有更次已完成，不能開始新更次"

        # Validate rest period
        if current_shift in rest_periods:
            required_rest = rest_periods[current_shift]
            if new_minutes < required_rest:
                return False, f"需要休息 {required_rest} 分鐘後才能開始新更次"

        next_shift = ShiftClassificationRules.get_next_available_shift(completed_shifts)
        
        if next_shift is None:
            return False, "所有更次已完成，不能開始新更次"
        
        if current_shift in completed_shifts:
            return False, f"{current_shift.value} 已經完成，不能重複開始"
        
        return True, f"可以開始 {next_shift.value}"

    def get_shift(self, shift_type: ShiftType) -> Optional[ShiftAttendance]:
        """Get specific shift by type"""
        for shift in self.shifts:
            if shift.shift_type == shift_type:
                return shift
        return None

    def has_shift(self, shift_type: ShiftType) -> bool:
        """Check if attendance record has a specific shift type"""
        return any(shift.shift_type == shift_type for shift in self.shifts)

    def get_shift_or_create(self, shift_type: ShiftType) -> ShiftAttendance:
        """Get shift or create if not exists"""
        existing_shift = self.get_shift(shift_type)
        if existing_shift:
            return existing_shift

        new_shift = ShiftAttendance(shift_type=shift_type)
        self.shifts.append(new_shift)
        return new_shift

    def remove_shift(self, shift_type: ShiftType) -> bool:
        """Remove a shift (useful for corrections)"""
        for i, shift in enumerate(self.shifts):
            if shift.shift_type == shift_type:
                del self.shifts[i]
                self.updated_at = get_this_moment()
                return True
        return False

    def get_daily_summary(self) -> Dict[str, Any]:
        """Get comprehensive daily attendance summary"""
        return {
            "worker_id": self.worker_id,
            "project_id": self.project_id,
            "attendance_date": self.attendance_date.isoformat(),
            "status": self.attendance_status.value,
            "total_shifts": self.daily_shift_count,
            "completed_shifts": len(self.completed_shifts),
            "pending_shifts": len(self.pending_shifts),
            "total_ot_hours": self.total_ot_hours,
            "total_raw_records": len(self.raw_records),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------

    @classmethod
    async def add_worker_attendance_record(cls,
                                           project_id: str,
                                           user_id: str,
                                              latitude: str,
                                              longitude: str,
                                              accuracy: str,
                                              timestamp: datetime,
                                              attendance_method: bool = True,
                                              image_file_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            
            if not latitude or not longitude or not accuracy:
                return {
                    "status": "error",
                    "message": "GPS座標和精度不能為空",
                    "data": None,
                }

            # Validate user and project exist (parallel queries)
            user_info, project_info = await asyncio.gather(
                User.find_one(User.id == ObjectId(user_id), User.deleted_at == None),
                Project.find_one(Project.id == ObjectId(project_id), Project.deleted_at == None),
                return_exceptions=True
            )
            
            if not user_info or isinstance(user_info, Exception):
                return {
                    "status": "error",
                    "message": "找不到用戶記錄",
                    "data": None,
                }
            
            if not project_info or isinstance(project_info, Exception):
                return {
                    "status": "error",
                    "message": "找不到項目記錄",
                    "data": None,
                }

            name = user_info.english_name if user_info.english_name else user_info.payee_name

            if image_file_ids:
                logging.info(f"📸 Image files: {len(image_file_ids)} files")

            timestamp_hk_date = timestamp.date()

            action_result = None
            attendance_record = None

            # Process attendance based on time
            # Use 30-hour clock logic: times before 6 AM are considered part of previous day
            if timestamp.time() < time(6, 0):
                logging.info("🔄 Handling early morning attendance (before 6 AM)")
                action_result, attendance_record = await cls._handle_early_morning_attendance(user_id, 
                                                                                            project_id, 
                                                                                            latitude, 
                                                                                            longitude, 
                                                                                            accuracy,
                                                                                            timestamp, 
                                                                                            timestamp_hk_date, 
                                                                                            attendance_method, 
                                                                                            image_file_ids
                                                                                            )

            else:
                logging.info("🔄 Handling normal attendance (6 AM and later)")
                action_result, attendance_record = await cls._handle_normal_attendance(user_id, 
                                                                                       project_id, 
                                                                                       latitude, 
                                                                                       longitude, 
                                                                                        accuracy,
                                                                                        timestamp, 
                                                                                        timestamp_hk_date, 
                                                                                        attendance_method, 
                                                                                        image_file_ids
                                                                                        )
                logging.info(f"🔍 Normal attendance result: {action_result}, attendance_record: {attendance_record}")


            if action_result and action_result.get("action_type") == "check_in" and not attendance_record:
                logging.info("🔄 Creating new attendance record for current day")
                attendance_record = await cls._create_new_attendance_record(user_id, 
                                                                            project_id, 
                                                                            timestamp_hk_date)

                action_result = await cls._determine_and_process_check_action(attendance_record, 
                                                                              latitude, 
                                                                              longitude, 
                                                                              accuracy,
                                                                              timestamp, 
                                                                              attendance_method, 
                                                                              image_file_ids
                                                                              )
            
            if not action_result or not action_result.get("success", False):
                error_message = action_result.get("message", "Error processing attendance record") if action_result else "Cannot process attendance record"
                logging.error(f"❌ Attendance action failed: {error_message}")
                return {
                    "status": "error",
                    "message": error_message,
                    "data": {"details": action_result.get("details", {})} if action_result else {},
                }

            project_location = project_info.project_title

            image_urls = [] 
            if action_result["success"]:
                action_type = action_result.get("action_type", "unknown")
                # Check if attendance_record exists before accessing attendance_date
                date_comparison = "today's" if attendance_record and attendance_record.attendance_date == timestamp_hk_date else "yesterday's"
                response_message = f"✅ Hi, {name}. Successfully {'checked in' if action_type == 'check_in' else 'checked out'} for {date_comparison} shift.\n成功打卡！\n\n"

                response_message += f"📍 Location / 位置: {project_location}\n"
                response_message += f"🕐 Time / 時間: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} HKT\n"

                if not attendance_method:  # Image attendance
                    if image_file_ids:
                        for i, image_file_id in enumerate(image_file_ids):
                            attendance_image_url = (
                                f"{i+1}. {base_url}/attendance-images/{image_file_id}"
                            )
                            image_urls.append(attendance_image_url)
                        response_message += "📷 Images / 圖片:\n"
                        for image_url in image_urls:
                            response_message += f"{image_url}\n"
                    else:
                        response_message += "📷 No images / 沒有圖片\n"
                # For GPS attendance, no image-related message is added
            else:
                response_message = f"❌ {action_result['message']}"

            # Save the updated record
            if attendance_record:
                await attendance_record.save()

            # Trigger PDF update check (this runs asynchronously)
            asyncio.create_task(
                cls.trigger_pdf_update_if_needed(project_id, change_threshold=1)
            )


            return {
                "status": "success",
                "message": response_message,
                "data": {
                    "attendance_record": attendance_record.model_dump(exclude={"_id"}) if attendance_record else {},
                    "action_details": action_result.get("details", {}),
                    "image_urls": image_urls,
                },
            }

        except ValueError as ve:
            logging.error(f"Validation error in add_worker_attendance_record: {str(ve)}")
            return {
                "status": "error",
                "message": f"數據驗證錯誤: {str(ve)}",
                "data": {"error_type": "validation_error", "details": str(ve)},
            }
        except decimal.ConversionSyntax as cse:
            logging.error(f"Decimal conversion error in add_worker_attendance_record: {str(cse)}")
            return {
                "status": "error",
                "message": f"座標數據格式錯誤: {str(cse)}",
                "data": {"error_type": "coordinate_error", "details": str(cse)},
            }
        except Exception as e:
            logging.error(f"Unexpected error in add_worker_attendance_record: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "message": f"Unexpected error processing attendance record: {str(e)}",
                "data": {"error_type": "unexpected_error", "details": str(e)},
            }





    @classmethod
    async def _determine_and_process_check_action(
        cls,
        attendance_record: "AttendanceRecord",
        latitude: str,
        longitude: str,
        accuracy: str,
        timestamp: datetime,
        attendance_method: bool,
        image_file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        try:
            action_type = await cls._determine_action_type(
                attendance_record=attendance_record,
                timestamp=timestamp,
                attendance_method=attendance_method,
                image_file_ids=image_file_ids
            )
            logging.info(
                f"🔄 Action type in _determine_and_process_check_action: {action_type}, "
                f"attendance_record: {attendance_record}, "
                f"timestamp: {timestamp}"
            )

            if action_type == "check_in" and attendance_record and attendance_record.attendance_date == timestamp.date():
                result = await attendance_record._process_check_in(
                    latitude,
                    longitude,
                    accuracy,
                    timestamp,
                    attendance_method,
                    image_file_ids,
                )

                logging.info(f"🔍 Process check-in result: {result}")

                if result[0]:  # success
                    return {
                        "success": True,
                        "message": result[1],
                        "details": result[2],
                        "action_type": "check_in",
                        "shift_type": result[2].get("shift_type", "unknown"),
                    }
                else:
                    return {
                        "success": False,
                        "message": result[1],
                        "details": result[2],
                        "action_type": "check_in",
                    }
            elif action_type == "check_in" and attendance_record and attendance_record.attendance_date != timestamp.date():
                result = await cls._handle_normal_attendance(
                    attendance_record.worker_id,
                    attendance_record.project_id,
                    latitude,
                    longitude,
                    accuracy,
                    timestamp,
                    attendance_record.attendance_date,
                    attendance_method,
                    image_file_ids,
                )
                return result


            elif action_type == "check_out":

                result = await attendance_record._process_check_out(
                    latitude,
                    longitude,
                    accuracy,
                    timestamp,
                    attendance_method,
                    image_file_ids,
                )

                if result[0]:  # success
                    return {
                        "success": True,
                        "message": result[1],
                        "details": result[2],
                        "action_type": "check_out",
                        "shift_type": result[2].get("shift_type", "unknown"),
                    }
                else:
                    return {
                        "success": False,
                        "message": result[1],
                        "details": result[2],
                        "action_type": "check_out",
                    }
            else:
                return {
                    "success": False,
                    "message": "Unable to determine action type",
                    "details": {},
                    "action_type": "unknown",
                }

        except Exception as e:
            logging.error(f"Error determining attendance action: {str(e)}")
            return {
                "success": False,
                "message": f"處理打卡操作時發生錯誤: {str(e)}",
                "details": {},
                "action_type": "error",
            }

    @classmethod
    async def _determine_action_type(
        cls,
        attendance_record: "AttendanceRecord",
        timestamp: datetime,
        attendance_method: bool,
        image_file_ids: Optional[List[str]] = None,
    ) -> str:

        logging.info(f"🔍 Determining action type for timestamp: {timestamp}")
        
        if not attendance_record.shifts:
            logging.info("🔍 No existing shifts, returning check_in")
            return "check_in"

        # Check for pending shifts (checked in but not out)
        pending_shifts = [
            shift
            for shift in attendance_record.shifts
            if shift.effective_check_in and not shift.effective_check_out
        ]

        if pending_shifts:
            logging.info(f"🔍 Found {len(pending_shifts)} pending shifts")

            # For each pending shift, validate if the time makes sense for check-out
            for shift in pending_shifts:
                shift_type = shift.shift_type
                logging.info(f"🔍 Checking pending shift type: {shift_type}")

                try:
                    # Create a temporary check-out record to validate timing
                    temp_record = CheckInOutRecord(
                        check_type=CheckType.CHECK_OUT,
                        timestamp=timestamp,
                        latitude="0.0",
                        longitude="0.0",
                        accuracy="0",
                        attendance_method=attendance_method,
                        image_file_ids=image_file_ids,
                    )

                    # Validate if this time makes sense for check-out of this shift type
                    is_valid, message = await temp_record.validate_for_shift_type(shift_type=shift.shift_type)
                    if not is_valid:
                        logging.info(f"🔍 Validation failed for shift {shift.shift_type.value}: {message}")
                        continue
                    else:
                        logging.info(f"✅ Valid checkout time for shift {shift.shift_type.value}")
                        return "check_out"
                except Exception as e:
                    logging.error(f"Error validating checkout time: {str(e)}")
                    continue

            # If we get here, no pending shift could accommodate this check-out time, treat as new check-in
            logging.info(
                "🔍 No pending shift can accommodate this time, treating as new check_in"
            )
            return "check_in"

        # No pending shifts, determine if this could be a new check-in
        return "check_in"

    async def _process_check_in(
        self,
        latitude: str,
        longitude: str,
        accuracy: str,
        timestamp: datetime,
        attendance_method: bool,
        image_file_ids: Optional[List[str]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Process check-in with shift determination"""

        logging.info(f"🔄 Processing check-in with timestamp: {timestamp}")

        # Determine what shift this check-in could be for
        shift_type, explanation = ShiftClassificationRules.classify_shift(timestamp, None, self.shifts)
        logging.info(f"shift type is {shift_type}, and explanation is {explanation}")

        # Check if this shift already has a pending check-in (allow multiple cycles)
        existing_shift = self.get_shift(shift_type)
        if existing_shift:
            # Only prevent check-in if there's an unpaired check-in (no corresponding check-out)
            # This allows multiple check-in/check-out cycles within the same shift
            if (
                existing_shift.effective_check_in
                and not existing_shift.effective_check_out
            ):
                return (
                    False,
                    f"You have already checked in for this shift. Please check out first.",
                    {"existing_checkin": existing_shift.effective_check_in.isoformat()},
                )

        # Create check-in record
        try:
            logging.info(
                f"🔄 Creating CheckInOutRecord with timestamp: {timestamp}"
            )

            record = CheckInOutRecord(
                check_type=CheckType.CHECK_IN,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy,
                timestamp=timestamp,
                attendance_method=attendance_method,
                image_file_ids=image_file_ids,
            )
        except Exception as e:
            logging.error(f"Error creating CheckInOutRecord: {str(e)}")
            return False, f"Error creating check-in record: {str(e)}", {}

        # Store in raw records
        self.raw_records.append(record)

        # Add to shift
        shift_attendance = self.get_shift_or_create(shift_type)
        success, message = await shift_attendance.add_check_in_out_record(record)
        if not success:
            return False, message, {}

        self.updated_at = get_this_moment()

        return (
            True,
            f"Successfully checked in for {shift_type.value} shift",
            {
                "action": "check_in",
                "shift_type": shift_type.value,
                "shift_explanation": explanation,
                "timestamp": timestamp.isoformat(),
            },
        )

    async def _process_check_out(
        self,
        latitude: str,
        longitude: str,
        accuracy: str,
        timestamp: datetime,
        attendance_method: bool,
        image_file_ids: Optional[List[str]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Process check-out with shift finalization"""

        # Find which shift this checkout belongs to by looking at pending check-ins
        pending_shift = None
        for shift in self.shifts:
            if shift.effective_check_in and not shift.effective_check_out:
                pending_shift = shift
                break

        if not pending_shift:
            return False, "搵唔到待簽退嘅記錄。請先簽到。", {}

        # Validate this checkout time makes sense for the shift
        logging.info(
            f"🔄 Processing checkout - Current shift type: {pending_shift.shift_type.value}"
        )
        logging.info(
            f"📍 Check-in time: {pending_shift.effective_check_in.time()}, Check-out time: {timestamp.time()}"
        )

        logging.info(f"🔄 Checkout timestamp: {timestamp}")

        final_shift_type, explanation = ShiftClassificationRules.classify_shift(
            pending_shift.effective_check_in, timestamp
        )

        logging.info(
            f"📋 Shift classification result: {final_shift_type.value if final_shift_type else 'None'}, Explanation: {explanation}"
        )

        if not final_shift_type:
            return False, f"錯誤: 簽到／簽出時間唔符合規定: {explanation}", {}

        try:

            logging.info(
                f"🔄 Creating checkout CheckInOutRecord with timestamp: {timestamp}"
            )

            record = CheckInOutRecord(
                check_type=CheckType.CHECK_OUT,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy,
                timestamp=timestamp,
                attendance_method=attendance_method,
                image_file_ids=image_file_ids,
            )
        except Exception as e:
            logging.error(f"Error creating CheckInOutRecord for checkout: {str(e)}")
            return False, f"創建簽退記錄時發生錯誤: {str(e)}", {}

        # Store in raw records
        self.raw_records.append(record)

        # Handle shift type change (morning -> full day)
        if final_shift_type != pending_shift.shift_type:
            logging.info(
                f"🔄 Changing shift type from {pending_shift.shift_type.value} to {final_shift_type.value}"
            )
            # Update the shift type directly
            pending_shift.shift_type = final_shift_type
        else:
            logging.info(f"✅ Shift type unchanged: {pending_shift.shift_type.value}")

        success, message = await pending_shift.add_check_in_out_record(record)
        if not success:
            return False, message, {}

        self.updated_at = get_this_moment()

        # Generate detailed response
        details = {
            "action": "check_out",
            "shift_type": final_shift_type.value,
            "shift_explanation": explanation,
            "timestamp": timestamp.isoformat(),
            "shift_summary": {
                "is_late_check_in": pending_shift.is_late_check_in,
                "is_early_check_out": pending_shift.is_early_check_out,
                "ot_hours": pending_shift.ot_hours,
            },
        }

        return True, f"成功簽退 {final_shift_type.value} 更次", details

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    @classmethod
    async def get_all_attendance_records_for_project(
        cls, project_id: str, deleted_at: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get ALL attendance records for a project (for PDF generation)"""
        try:
            # Get all attendance records for the project without month/year filtering
            attendance_records = await cls.find(
                cls.project_id == project_id, cls.deleted_at == deleted_at
            ).to_list()

            if not attendance_records:
                logging.info(f"No attendance records found for project {project_id}")
                return []

            logging.info(
                f"Found {len(attendance_records)} total attendance records for project {project_id}"
            )

            # Get unique worker IDs to fetch their names
            worker_ids = set()
            for record in attendance_records:
                if record.worker_id:
                    worker_ids.add(record.worker_id)

            worker_names = {}
            for worker_id in worker_ids:
                try:
                    user = await User.find_one(
                        User.id == ObjectId(worker_id), User.deleted_at == None
                    )
                    if user:
                        worker_names[worker_id] = {
                            "payee_name": user.payee_name,
                        }
                except Exception as e:
                    logging.warning(
                        f"Error fetching user info for worker {worker_id}: {str(e)}"
                    )
                    worker_names[worker_id] = {
                        "payee_name": None,
                    }

            attendance_record_list = []

            for record in attendance_records:
                try:
                    daily_summary = record.get_daily_summary()
                    if daily_summary:

                        worker_info = worker_names.get(record.worker_id, {})
                        daily_summary["payee_name"] = worker_info.get(
                            "payee_name"
                        )

                        attendance_record_list.append(daily_summary)
                except Exception as e:
                    logging.warning(
                        f"Error getting daily summary for record {record.id}: {str(e)}"
                    )
                    continue

            logging.info(
                f"Successfully processed {len(attendance_record_list)} attendance records"
            )
            return attendance_record_list

        except Exception as e:
            logging.error(
                f"Error in get_all_attendance_records_for_project for project {project_id}: {str(e)}"
            )
            return []

    @classmethod
    async def get_attendance_records_by_month_year_for_project(
        cls, project_id: str, deleted_at: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get attendance records organized by month and year for comprehensive PDF generation"""
        try:
            logging.info(
                f"🔍 Starting to fetch attendance records for project {project_id}"
            )

            # Validate project_id format
            try:
                from bson import ObjectId

                object_id = ObjectId(project_id)
                logging.info(f"✅ Valid ObjectId format: {object_id}")
            except Exception as oid_error:
                logging.error(
                    f"❌ Invalid ObjectId format for project_id {project_id}: {str(oid_error)}"
                )
                return {}

            # First, let's check if there are any attendance records at all
            try:
                total_count = await cls.find(cls.deleted_at == deleted_at).count()
                project_count = await cls.find(
                    cls.project_id == project_id, cls.deleted_at == deleted_at
                ).count()
                logging.info(f"Total attendance records in database: {total_count}")
                logging.info(
                    f"Attendance records for project {project_id}: {project_count}"
                )

                # Check for records with different deleted_at values
                all_project_records = await cls.find(
                    cls.project_id == project_id
                ).count()
                logging.info(
                    f"Total records for project {project_id} (any deleted_at): {all_project_records}"
                )

                # Check for records with None deleted_at specifically
                none_deleted_count = await cls.find(
                    cls.project_id == project_id, cls.deleted_at == None
                ).count()
                logging.info(
                    f"Records for project {project_id} with deleted_at == None: {none_deleted_count}"
                )
            except Exception as count_error:
                logging.warning(
                    f"Count method not available, using alternative: {str(count_error)}"
                )
                # Fallback: get all records and count manually
                all_records = await cls.find().to_list()
                project_records = await cls.find(cls.project_id == project_id).to_list()
                project_records_none_deleted = await cls.find(
                    cls.project_id == project_id, cls.deleted_at == None
                ).to_list()

                total_count = len(all_records)
                project_count = len(project_records)
                all_project_records = len(project_records)
                none_deleted_count = len(project_records_none_deleted)

                logging.info(
                    f"Fallback counts - Total: {total_count}, Project: {project_count}, None deleted: {none_deleted_count}"
                )

            # Get all attendance records for the project
            attendance_records = await cls.find(
                cls.project_id == project_id, cls.deleted_at == deleted_at
            ).to_list()

            # If no records found with the specified deleted_at filter, try without it
            if not attendance_records and deleted_at is not None:
                logging.info(
                    f"No records found with deleted_at == {deleted_at}, trying without filter..."
                )
                attendance_records = await cls.find(
                    cls.project_id == project_id
                ).to_list()
                logging.info(
                    f"Found {len(attendance_records)} records without deleted_at filter"
                )

            if not attendance_records:
                logging.info(f"No attendance records found for project {project_id}")
                return {}

            logging.info(
                f"Found {len(attendance_records)} total attendance records for project {project_id}"
            )

            # Log sample record structure
            if attendance_records:
                sample_record = attendance_records[0]
                logging.info(f"Sample record type: {type(sample_record)}")
                logging.info(f"Sample record ID: {sample_record.id}")
                logging.info(f"Sample record worker_id: {sample_record.worker_id}")
                logging.info(
                    f"Sample record attendance_date: {sample_record.attendance_date}"
                )
                logging.info(
                    f"Sample record shifts count: {len(sample_record.shifts) if hasattr(sample_record, 'shifts') else 'No shifts'}"
                )

            # Get unique worker IDs to fetch their names
            worker_ids = set()
            for record in attendance_records:
                if record.worker_id:
                    worker_ids.add(record.worker_id)

            logging.info(
                f"Found {len(worker_ids)} unique worker IDs: {list(worker_ids)[:5]}..."
            )

            worker_names = {}
            for worker_id in worker_ids:
                try:
                    user = await User.find_one(
                        User.id == ObjectId(worker_id), User.deleted_at == None
                    )
                    if user:
                        worker_names[worker_id] = {
                            "payee_name": user.payee_name,
                        }
                        logging.info(
                            f"Found worker {worker_id}: {user.payee_name}"
                        )
                    else:
                        logging.warning(f"No user found for worker_id {worker_id}")
                        worker_names[worker_id] = {
                            "payee_name": None,
                        }
                except Exception as e:
                    logging.warning(
                        f"Error fetching user info for worker {worker_id}: {str(e)}"
                    )
                    worker_names[worker_id] = {
                        "payee_name": None,
                    }

            # Organize records by month and year
            organized_records = {}

            for record in attendance_records:
                try:
                    if not record.attendance_date:
                        logging.warning(
                            f"Record {record.id} has no attendance_date, skipping"
                        )
                        continue

                    # Create month-year key
                    month_year_key = f"{record.attendance_date.year}-{record.attendance_date.month:02d}"

                    if month_year_key not in organized_records:
                        organized_records[month_year_key] = []

                    daily_summary = record.get_daily_summary()
                    if daily_summary:
                        # Add worker name information
                        worker_info = worker_names.get(record.worker_id, {})
                        daily_summary["payee_name"] = worker_info.get(
                            "payee_name"
                        )

                        organized_records[month_year_key].append(daily_summary)
                        logging.info(
                            f"Added record for {month_year_key}, worker {record.worker_id}"
                        )
                    else:
                        logging.warning(
                            f"Failed to get daily summary for record {record.id}"
                        )

                except Exception as e:
                    logging.warning(f"Error processing record {record.id}: {str(e)}")
                    continue

            # Sort records within each month by date
            for month_key in organized_records:
                organized_records[month_key].sort(
                    key=lambda x: x.get("attendance_date", "")
                )

            logging.info(
                f"Successfully organized {len(organized_records)} months of attendance records"
            )
            logging.info(f"Month keys: {list(organized_records.keys())}")
            for month_key, records in organized_records.items():
                logging.info(f"Month {month_key}: {len(records)} records")

            return organized_records

        except Exception as e:
            logging.error(
                f"Error in get_attendance_records_by_month_year_for_project for project {project_id}: {str(e)}"
            )
            return {}

    @classmethod
    async def get_attendance_records_for_each_project(
        cls, project_id: str, deleted_at: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get attendance records for a project"""
        try:
            attendance_records = await cls.find(
                cls.project_id == project_id, cls.deleted_at == deleted_at
            ).to_list()

            # Get the month and year from the attendance_records
            months = set()
            years = set()
            for record in attendance_records:
                if hasattr(record, "attendance_date") and record.attendance_date:
                    months.add(record.attendance_date.month)
                    years.add(record.attendance_date.year)

            if not months or not years:
                logging.warning(
                    f"No valid dates found in attendance records for project {project_id}"
                )
                return []

            # Use the most recent month/year for filtering
            month = max(months)
            year = max(years)

            attendance_record_list = []

            # Get the attendance records for the specific month/year
            filtered_records = await cls.find(
                cls.project_id == project_id,
                cls.deleted_at == deleted_at,
                cls.attendance_date.month == month,
                cls.attendance_date.year == year,
            ).to_list()

            logging.info(
                f"Found {len(filtered_records)} attendance records for project {project_id} in {year}-{month}"
            )

            for record in filtered_records:
                try:
                    daily_summary = record.get_daily_summary()
                    if daily_summary:
                        attendance_record_list.append(daily_summary)
                except Exception as e:
                    logging.warning(
                        f"Error getting daily summary for record {record.id}: {str(e)}"
                    )
                    continue

            logging.info(
                f"Successfully processed {len(attendance_record_list)} attendance records"
            )
            return attendance_record_list

        except Exception as e:
            logging.error(
                f"Error in get_attendance_records_for_each_project for project {project_id}: {str(e)}"
            )
            return []

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    @classmethod
    async def get_grouped_day_entries_for_payslip(
        cls,
        *,
        month: int,
        year: int,
    ) -> List[Dict[str, Any]]:

        if month < 1 or month > 12:
            raise ValueError("月份必須喺1到12之間")

        start_date = date(year, month, 1)
        if month == 12:
            next_month_date = date(year + 1, 1, 1)
        else:
            next_month_date = date(year, month + 1, 1)

        filters = [
            cls.attendance_date >= start_date,
            cls.attendance_date < next_month_date,
            cls.deleted_at == None,
        ]

        logging.info(f"filters in get_grouped_day_entries_for_payslip: {filters}")
        logging.info(f"start_date: {start_date}")
        logging.info(f"next_month_date: {next_month_date}")

        # Sort by project, worker, then date for efficient grouping
        records = (
            await cls.find(*filters)
            .sort(cls.project_id, cls.worker_id, cls.attendance_date)
            .to_list()
        )

        logging.info(f"records in get_grouped_day_entries_for_payslip: {records}")
        logging.info(f"records count: {len(records)}")

        if not records:
            return []

        # Group: project_id -> worker_id -> day -> entry
        projects: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}

        for rec in records:
            project_key = str(rec.project_id)
            worker_key = str(rec.worker_id)
            day_num = rec.attendance_date.day

            # Initialize nested dictionaries
            if project_key not in projects:
                projects[project_key] = {}
            if worker_key not in projects[project_key]:
                projects[project_key][worker_key] = {}

            # Process shifts to determine morning/afternoon work and OT hours
            morning_worked = False
            afternoon_worked = False
            total_ot_hours = Decimal(0)

            for shift in rec.shifts:
                # Only count completed shifts for morning/afternoon credit
                if not shift.is_complete:
                    continue

                if shift.shift_type == ShiftType.FULL_DAY_1:
                    morning_worked = True
                    afternoon_worked = True
                    # Add standard OT from full day shift
                    try:
                        ot_value = shift.ot_hours
                        if ot_value is not None:
                            if isinstance(ot_value, str):
                                ot_str = ot_value.strip()
                                total_ot_hours += (
                                    Decimal(ot_str) if ot_value else Decimal(0)
                                )
                            else:
                                ot_str = str(ot_value).strip()
                                total_ot_hours += (
                                    Decimal(ot_str)
                                    if ot_str and ot_str != "None"
                                    else Decimal(0)
                                )
                    except (
                        ValueError,
                        TypeError,
                        decimal.InvalidOperation,
                        decimal.ConversionSyntax,
                    ) as e:
                        logging.warning(
                            f"Invalid OT hours for full_day shift: {shift.ot_hours}, error: {e}"
                        )
                        total_ot_hours += Decimal(0)

                elif shift.shift_type == ShiftType.FULL_DAY_2:
                    morning_worked = True
                    # Full day_2 shifts don't generate standard OT
                    total_ot_hours += Decimal(0)

                elif shift.shift_type == ShiftType.FULL_DAY_3:
                    afternoon_worked = True
                    # Full day_3 shifts don't generate standard OT
                    total_ot_hours += Decimal(0)


                elif shift.shift_type == ShiftType.FULL_DAY_4:
                    # Full day_4 shifts don't generate standard OT
                    total_ot_hours += Decimal(0)

            # Store the day entry
            projects[project_key][worker_key][day_num] = {
                "day": day_num,
                "morning": morning_worked,
                "afternoon": afternoon_worked,
                "ot": str(total_ot_hours),
            }

        # Build the final nested output structure
        grouped_output = []
        for project_id in sorted(projects.keys()):
            workers_list = []
            for worker_id in sorted(projects[project_id].keys()):
                day_entries = projects[project_id][worker_id]
                # Sort entries by day
                sorted_entries = [
                    day_entries[day] for day in sorted(day_entries.keys())
                ]

                workers_list.append(
                    {
                        "worker_id": worker_id,
                        "entries": sorted_entries,
                    }
                )

            grouped_output.append(
                {
                    "project_id": project_id,
                    "workers": workers_list,
                }
            )

        return grouped_output

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------

    @classmethod
    def _get_shift_display_name(cls, shift_type: ShiftType) -> str:
        """Get user-friendly shift names"""
        shift_names = {
            ShiftType.FULL_DAY_1: "Shift 1",
            ShiftType.FULL_DAY_2: "shift 2",
            ShiftType.FULL_DAY_3: "shift 3",
            ShiftType.FULL_DAY_4: "shift 4",
        }
        return shift_names.get(shift_type, shift_type.value)

    @classmethod
    def _can_work_additional_shifts(
        cls, attendance_record: "AttendanceRecord", completed_shift: ShiftType
    ) -> bool:
        """Check if worker can take on additional shifts after completing one (sequential consumption)"""

        completed_shifts = set(attendance_record.completed_shifts)
        
        # Check if there are any shifts remaining to be consumed
        next_shift = ShiftClassificationRules.get_next_available_shift(completed_shifts)
        return next_shift is not None

    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------

    @classmethod
    async def get_attendance_info(
        cls, user_waba: str, link_type: str = "gps"
    ) -> Dict[str, Any]:

        from src.routes.attendance_via_gps_routes import \
            generate_gps_attendance_link
        from src.routes.attendance_via_image_routes import \
            generate_image_attendance_link

        try:
            # 1. Generate check-in URL based on link type
            if link_type == "image":
                checkin_url = await generate_image_attendance_link(user_waba)
            else:
                checkin_url = await generate_gps_attendance_link(user_waba)

            # 2. Validate and get user information
            user_validation = await cls._validate_and_get_user(user_waba)
            if user_validation["status"] == "error":
                return user_validation

            user_id = user_validation["user_id"]
            name = user_validation["name"]

            # 3. Get today's date in HK timezone

            timestamp_result = get_this_moment()
            logging.info(
                f"standardize_timestamp result: {timestamp_result}, type: {type(timestamp_result)}"
            )

            today = timestamp_result.astimezone(HK_TZ).date()
            logging.info(
                f"Checking attendance for {name} on {today}, type: {type(today)}"
            )

            # 4. Get all attendance records for today (multiple projects possible)
            attendance_records = await cls._get_today_attendance_records(user_id, today)

            # 5. Analyze attendance status across all projects
            attendance_analysis = await cls._analyze_attendance_status(
                attendance_records
            )

            # 6. Generate comprehensive response
            response = await cls._generate_attendance_response(attendance_analysis, 
                                                               name, 
                                                               checkin_url, 
                                                               attendance_records,
                                                               link_type
            )

            logging.info(f"Attendance info for {name}: {response['attendance_status']}")
            return response

        except Exception as e:
            logging.error(f"Error in get_attendance_info: {str(e)}")
            return {
                "attendance_status": AttendanceStatus.ERROR.value,
                "message": f"系統錯誤，請稍後再試: {str(e)}",
                "data": None,
            }

    @classmethod
    async def _generate_attendance_response(
        cls,
        analysis: Dict[str, Any],
        name: str,
        checkin_url: str,
        attendance_records: List["AttendanceRecord"],
        link_type: str
    ) -> Dict[str, Any]:
        """Generate comprehensive response message based on actual attendance status"""

        try:
            status = analysis["status"]
            overall_stats = analysis["overall_summary"]
            projects = analysis.get("projects", [])

            # Handle NO_RECORD status
            if status == AttendanceStatus.NO_RECORD:
                if link_type == "image":
                    message = f"Hi {name}, you haven't started your work today yet.\n你今日都仲未開始工作喎～\n\n"
                    message += "⏰ Check in link is valid for 15 minutes, please use it quickly.\n簽到連結有效期為15分鐘，請盡快使用。"
                else:
                    message = f"Hi {name}, you haven't started your work today yet.\n你今日都仲未開始工作喎～\n\n"
                    message += f"🔗 Click the link below to check in/請點擊以下連結簽到: \n{checkin_url}\n\n"
                    message += "⏰ Check in link is valid for 15 minutes, please use it quickly.\n簽到連結有效期為15分鐘，請盡快使用。"

                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {
                        "has_pending_work": False,
                        "next_action": "check_in",
                        "analysis": analysis,
                    },
                }

            # Handle CHECKED_IN_PENDING status
            elif status == AttendanceStatus.CHECKED_IN_PENDING:

                pending_shifts = []
                projects = analysis.get("projects", [])
                for project in projects:
                    for shift in project.get("shifts", []):
                        if shift.get("checked_in") and not shift.get("checked_out"):
                            shift_name = cls._get_shift_display_name_from_str(
                                shift.get("shift_type", "")
                            )
                            pending_shifts.append(shift_name)

                if pending_shifts:
                    message = f"👋 Hi, {name}! "
                else:
                    message = f"👋 Hi {name}, you have already clocked in, waiting for clock out.\n\n您已經打卡，等待簽退。\n\n"

                # Add project details
                if projects:
                    message += "You have the following shift to clock out / 您有以下更次需要簽退: \n"
                    for project in projects:
                        message += f"📍 Location / 位置: {project.get('project_title', 'Unknown project')}\n"
                        for shift in project.get("shifts", []):
                            if shift.get("checked_in") and not shift.get("checked_out"):
                                check_in_time = shift.get("check_in_time", "Unknown")
                                message += f"   • {check_in_time} (waiting for check out / 等待簽退)"
                        
                    message += "\n\n⏰ Check out link is valid for 15 minutes, please use it quickly.\n⏰ 簽退連結有效期為15分鐘，請盡快使用。\n\n"


                if link_type == "image":
                    message += f"Please upload the image and get the location information to check out.\n請上傳圖片並獲取位置信息以簽退。"
                else:
                    message += f"🔗 Click the link below to check out.\n🔗 請點擊以下連結簽退。\n\n{checkin_url}\n\n"


                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {
                        "has_pending_work": True,
                        "next_action": "check_out",
                        "pending_check_outs": overall_stats.get(
                            "pending_check_outs", 0
                        ),
                        "analysis": analysis,
                    },
                }

            elif status in [
                AttendanceStatus.SHIFT_COMPLETED,
                AttendanceStatus.FULL_DAY_COMPLETED,
            ]:
                # Get completed shift details from projects
                completed_shift_names = []
                projects = analysis.get("projects", [])
                for project in projects:
                    for shift in project.get("shifts", []):
                        if shift.get("completed"):
                            shift_name = cls._get_shift_display_name_from_str(
                                shift.get("shift_type", "")
                            )
                            completed_shift_names.append(shift_name)

                today = get_this_day()
                shifts_text = (
                    "、".join(set(completed_shift_names))
                    if completed_shift_names
                    else "工作"
                )
                message = f"✅ Hi, {name}! Here are your today's attendance details/你今日的打卡詳情如下: \n\n"

                # Add work summary
                for project in projects:
                    message += f"📅 Date / 日期: {today.strftime('%Y-%m-%d')}\n"
                    message += f"📍 Location / 位置: {project.get('project_title')}\n"
                    
                    for shift in project.get("shifts", []):
                        if shift.get("completed"):
                            check_in = shift.get("check_in_time", "Unknown")
                            check_out = shift.get("check_out_time", "Unknown")
                            message += f"   • {check_in} - {check_out}\n"

                # Check if can do more shifts
                can_do_more = cls._can_do_additional_shifts(projects)
                if can_do_more:
                    if link_type == "image":
                        message += f"\nIf you want to do other shifts, you can continue to check in.\n如欲進行其他更次，請上傳圖片繼續打卡。\n{checkin_url}\n"
                    else:
                        message += f"\nIf you want to do other shifts, you can continue to check in.\n如欲進行其他更次，請點擊以下連結繼續打卡。\n{checkin_url}"
                else:
                    message += "Sorry, the maximum number of shifts has been reached.\n對不起，您已經達到最大打卡次數。\n"
                    message += "\nThank you for your hard work!\n感謝您的辛勞！"

                total_ot = overall_stats.get("total_ot_hours", 0)

                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {
                        "has_pending_work": can_do_more,
                        "next_action": (
                            "additional_work" if can_do_more else "completed"
                        ),
                        "completed_shifts": overall_stats.get("completed_shifts", 0),
                        "total_ot_hours": total_ot,
                        "analysis": analysis,
                    },
                }

            elif status == AttendanceStatus.PARTIAL_DAY:
                message = f"Hi {name}, you have completed some work today, but there is still something to handle:\n你今日已完成部分工作，但仍有部分工作需要處理: \n\n"

                # Show completed and pending work
                projects = analysis.get("projects", [])
                for project in projects:
                    message += f"📍 {project.get('project_title', 'Unknown project')}\n"
                    for shift in project.get("shifts", []):
                        shift_name = cls._get_shift_display_name_from_str(
                            shift.get("shift_type", "")
                        )
                        if shift.get("completed"):
                            check_in = shift.get("check_in_time", "Unknown")
                            check_out = shift.get("check_out_time", "未知")
                            message += f"   ✅ {shift_name}: {check_in} - {check_out}\n"
                        elif shift.get("checked_in"):
                            check_in = shift.get("check_in_time", "Unknown")
                            message += (
                                f"   ⏳ {shift_name}: {check_in} (waiting for check out/等待簽退)\n"
                            )
                        else:
                            message += f"   ⭕ {shift_name}: not started/未開始\n"

                message += f"\n🔗 Click the link below to handle remaining work/請點擊以下連結: \n{checkin_url}"

                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {
                        "has_pending_work": True,
                        "next_action": "mixed",
                        "analysis": analysis,
                    },
                }

            # Handle ANOMALOUS_ACTIVITY status
            elif status == AttendanceStatus.ANOMALOUS_ACTIVITY:
                message = (
                    f"Hi {name}！\n\n⚠️ Anomalous attendance activity detected\n\nPlease contact the project manager to confirm the record"
                )

                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {
                        "has_pending_work": False,
                        "next_action": "contact_admin",
                        "analysis": analysis,
                    },
                }

            # Handle any other status
            else:
                message = f"Hi {name}！\n\n📋 Attendance status: {status.value}\n\nIf you have any questions, please contact the administrator"

                return {
                    "status": "success",
                    "attendance_status": status.value,
                    "message": message,
                    "checkin_url": checkin_url,
                    "data": {"analysis": analysis},
                }

        except Exception as e:
            logging.error(f"Error generating attendance response: {str(e)}")
            return {
                "status": "error",
                "attendance_status": AttendanceStatus.ERROR.value,
                "message": "System error, please try again later",
                "checkin_url": checkin_url,
                "data": None,
            }

    @classmethod
    async def _validate_and_get_user(cls, user_waba: str) -> Dict[str, Any]:
        """Enhanced user validation with proper error handling"""

        from src.utils.standardization_helpers import \
            normalize_mobile_from_whatsapp

        try:
            result = normalize_mobile_from_whatsapp(user_waba)
            country_code = result.get("country_code")
            clean_phone = result.get("mobile_digits")

            if not country_code or not clean_phone:
                return {
                    "status": "error",
                    "attendance_status": AttendanceStatus.NO_RECORD.value,
                    "message": "Cannot parse phone number format",
                }

            user_id = await User.get_user_id_by_mobile(country_code, clean_phone)

            if not user_id:
                return {
                    "status": "error",
                    "attendance_status": AttendanceStatus.NO_RECORD.value,
                    "message": f"User record not found for phone number {country_code}{clean_phone}",
                }

            user_info = await User.find_one(
                User.id == ObjectId(user_id), User.deleted_at == None
            )
            if not user_info:
                return {
                    "status": "error",
                    "attendance_status": AttendanceStatus.NO_RECORD.value,
                    "message": "User data has been deleted or does not exist",
                }

            name = (
                user_info.payee_name
                if user_info.payee_name
                else user_info.english_name
            )

            return {
                "status": "success",
                "user_id": user_id,
                "name": name,
                "user_info": user_info,
            }

        except Exception as e:
            logging.error(f"Error validating user {user_waba}: {str(e)}")
            return {
                "status": "error",
                "attendance_status": AttendanceStatus.NO_RECORD.value,
                "message": "System error, please try again later",
            }

    @classmethod
    async def _get_today_attendance_records(
        cls, user_id: str, today: date
    ) -> List["AttendanceRecord"]:
        """Enhanced method to get attendance records with proper structure validation"""

        try:
            attendance_records = await AttendanceRecord.find(
                AttendanceRecord.worker_id == str(user_id),
                AttendanceRecord.attendance_date == today,
                AttendanceRecord.deleted_at == None,
            ).to_list()

            logging.info(
                f"Found {len(attendance_records)} attendance records for user {user_id} on {today}"
            )

            # Enhanced structure validation for your updated model
            if attendance_records:
                first_record = attendance_records[0]
                logging.info(f"First record ID: {first_record.id}")
                logging.info(f"First record shifts count: {len(first_record.shifts)}")

                # Log shift details using correct structure
                for shift_attendance in first_record.shifts:
                    logging.info(
                        f"Shift {shift_attendance.shift_type.value}: checkin={shift_attendance.effective_check_in}, checkout={shift_attendance.effective_check_out}"
                    )
                    logging.info(
                        f"Shift {shift_attendance.shift_type.value} records: {len(shift_attendance.check_in_out_records)}"
                    )

            return attendance_records

        except Exception as e:
            logging.error(
                f"Error getting attendance records for user {user_id} on {today}: {str(e)}"
            )
            return []

    @classmethod
    async def _analyze_attendance_status(
        cls, attendance_records: List["AttendanceRecord"]
    ) -> Dict[str, Any]:
        """Enhanced attendance analysis with updated structure support"""

        if not attendance_records:
            return {
                "status": AttendanceStatus.NO_RECORD,
                "projects": [],
                "shift_summary": {
                    "morning_shifts": {"total": 0, "checked_in": 0, "completed": 0},
                    "afternoon_shifts": {"total": 0, "checked_in": 0, "completed": 0},
                    "full_day_shifts": {"total": 0, "checked_in": 0, "completed": 0},
                    "overnight_shifts": {"total": 0, "checked_in": 0, "completed": 0},
                },
                "overall_summary": {
                    "total_shifts": 0,
                    "completed_shifts": 0,
                    "pending_check_outs": 0,
                    "total_ot_hours": Decimal(0),
                },
            }

            # Enhanced analysis using updated AttendanceRecord structure
        project_analyses = []
        shift_summary = {
            "morning_shifts": {"total": 0, "checked_in": 0, "completed": 0},
            "afternoon_shifts": {"total": 0, "checked_in": 0, "completed": 0},
            "full_day_shifts": {"total": 0, "checked_in": 0, "completed": 0},
            "overnight_shifts": {"total": 0, "checked_in": 0, "completed": 0},
        }

        overall_stats = {
            "total_shifts": 0,
            "completed_shifts": 0,
            "pending_check_outs": 0,
            "total_ot_hours": Decimal(0),
        }

        for record in attendance_records:
            try:
                project_analysis = await cls._analyze_single_project_attendance(record)
                project_analyses.append(project_analysis)

                # Aggregate statistics using proper computed fields
                overall_stats["total_shifts"] += len(record.shifts)
                overall_stats["completed_shifts"] += len(record.completed_shifts)
                overall_stats["pending_check_outs"] += len(record.pending_shifts)
                overall_stats["total_ot_hours"] += record.total_ot_hours

                # Count shift types properly
                for shift_attendance in record.shifts:
                    shift_key = f"{shift_attendance.shift_type.value}_shifts"
                    if shift_key in shift_summary:
                        shift_summary[shift_key]["total"] += 1
                        if shift_attendance.effective_check_in:
                            shift_summary[shift_key]["checked_in"] += 1
                        if shift_attendance.is_complete:
                            shift_summary[shift_key]["completed"] += 1

            except Exception as e:
                logging.error(
                    f"Error analyzing project attendance record {record.id}: {str(e)}"
                )
                continue

        # Determine overall status using enhanced logic
        overall_status = cls._determine_enhanced_status(overall_stats, shift_summary)

        return {
            "status": overall_status,
            "projects": project_analyses,
            "shift_summary": shift_summary,
            "overall_summary": overall_stats,
        }

    @classmethod
    async def _analyze_single_project_attendance(
        cls, record: "AttendanceRecord"
    ) -> Dict[str, Any]:
        """Enhanced single project analysis with updated structure support"""

        try:
            # Get project information
            project_info = await Project.find_one(
                Project.id == ObjectId(record.project_id), Project.deleted_at == None
            )
            project_title = project_info.project_title if project_info else "Unknown project"

            shift_details = []

            # Analyze each shift using updated structure
            for shift_attendance in record.shifts:
                try:
                    config = await shift_attendance.get_shift_configuration_with_user_hours(record.worker_id)

                    shift_info = {
                        "shift_type": shift_attendance.shift_type.value,
                        "scheduled_start": config.scheduled_start.strftime("%H:%M"),
                        "scheduled_end": config.scheduled_end.strftime("%H:%M"),
                        "checked_in": shift_attendance.effective_check_in is not None,
                        "checked_out": shift_attendance.effective_check_out is not None,
                        "completed": shift_attendance.is_complete,
                        "check_in_time": (
                            shift_attendance.effective_check_in.strftime("%H:%M")
                            if shift_attendance.effective_check_in
                            else None
                        ),
                        "check_out_time": (
                            shift_attendance.effective_check_out.strftime("%H:%M")
                            if shift_attendance.effective_check_out
                            else None
                        ),
                        "is_late_check_in": shift_attendance.is_late_check_in,
                        "is_early_check_out": shift_attendance.is_early_check_out,
                        "ot_hours": shift_attendance.ot_hours,
                    }
                    shift_details.append(shift_info)

                except Exception as e:
                    logging.error(
                        f"Error processing shift {shift_attendance.shift_type}: {str(e)}"
                    )
                    continue

            return {
                "project_id": record.project_id,
                "project_title": project_title,
                "shifts": shift_details,
                "total_shifts": len(shift_details),
                "completed_shifts": len(record.completed_shifts),
                "pending_check_outs": len(record.pending_shifts),
                "total_ot_hours": record.total_ot_hours,
                "attendance_status": record.attendance_status.value,
            }

        except Exception as e:
            logging.error(f"Error analyzing single project attendance: {str(e)}")
            return {
                "project_id": record.project_id,
                "project_title": "Error project",
                "shifts": [],
                "total_shifts": 0,
                "completed_shifts": 0,
                "pending_check_outs": 0,
                "total_ot_hours": Decimal(0),
                "attendance_status": AttendanceStatus.NO_RECORD.value,
            }

    @classmethod
    def _determine_enhanced_status(
        cls, overall_stats: Dict[str, Any], shift_summary: Dict[str, Any]
    ) -> AttendanceStatus:
        """Enhanced status determination with support for all shift types"""

        total_shifts = overall_stats["total_shifts"]
        completed_shifts = overall_stats["completed_shifts"]
        pending_check_outs = overall_stats["pending_check_outs"]

        # No activity
        if total_shifts == 0:
            return AttendanceStatus.NO_RECORD

        # Check for anomalous activity
        # Check for incomplete shifts (checked in but not completed for a long time)
        if pending_check_outs > 0:
            # If any shift has been pending for hours, it might be incomplete
            return AttendanceStatus.CHECKED_IN_PENDING

        # All shifts completed
        if completed_shifts == total_shifts:
            if completed_shifts == 1:
                return AttendanceStatus.SHIFT_COMPLETED
            else:
                return AttendanceStatus.FULL_DAY_COMPLETED

        # Some shifts completed, some not
        if completed_shifts > 0:
            return AttendanceStatus.PARTIAL_DAY

        return AttendanceStatus.NO_RECORD

    # Note: This method is deprecated and replaced by _determine_enhanced_status

    @classmethod
    def _get_shift_display_name_from_str(cls, shift_type_str: str) -> str:
        """Get display name from shift type string"""
        try:
            shift_type = ShiftType(shift_type_str)
            return cls._get_shift_display_name(shift_type)
        except (ValueError, AttributeError):
            return shift_type_str

    @classmethod
    def _can_do_additional_shifts(cls, projects: List[Dict[str, Any]]) -> bool:
        """Check if worker can do additional shifts based on sequential consumption"""
        completed_shift_types = set()
        for project in projects:
            for shift in project.get("shifts", []):
                if shift.get("completed"):
                    completed_shift_types.add(shift.get("shift_type"))

        # Use sequential consumption logic - check if there are any shifts remaining
        next_shift = ShiftClassificationRules.get_next_available_shift(completed_shift_types)
        return next_shift is not None



    @classmethod
    async def trigger_pdf_update_if_needed(
        cls, project_id: str, change_threshold: int = 1
    ) -> Dict[str, Any]:

        try:
            # Get recent changes count
            recent_records = await cls.find(
                cls.project_id == project_id,
                cls.deleted_at == None,
                cls.updated_at >= (get_this_moment() - timedelta(days=1)),
            ).to_list()

            if len(recent_records) < change_threshold:
                return {
                    "status": "below_threshold",
                    "project_id": project_id,
                    "changes_detected": len(recent_records),
                    "threshold": change_threshold,
                    "message": f"Number of changes ({len(recent_records)}) is below the threshold ({change_threshold})",
                }

            # Try to trigger Temporal.io workflow for PDF update
            try:
                from temporal_app.client import get_temporal_client

                client = await get_temporal_client()

                # Start the attendance PDF update workflow
                handle = await client.start_workflow(
                    "AttendancePDFUpdateWorkflow",
                    args=[project_id, False],  # project_id, force_regenerate
                    id=f"attendance-pdf-update-{project_id}-{get_this_moment().strftime('%Y%m%d%H%M%S')}",
                    task_queue="attendance-task-queue",
                )

                logging.info(
                    f"✅ Triggered attendance PDF update workflow for project {project_id}: {handle.id}"
                )

                return {
                    "status": "workflow_triggered",
                    "project_id": project_id,
                    "workflow_id": handle.id,
                    "changes_detected": len(recent_records),
                    "threshold": change_threshold,
                    "message": f"Due to {len(recent_records)} changes, the PDF update workflow has been triggered",
                }

            except ImportError as import_error:
                logging.warning(f"⚠️ Temporal.io not available: {str(import_error)}")
                # Fall through to direct PDF generation

            except Exception as temporal_error:
                logging.warning(
                    f"⚠️ Failed to trigger Temporal.io workflow: {str(temporal_error)}"
                )
                # Fall through to direct PDF generation

            # Fallback: generate PDF directly if Temporal.io fails or is not available
            try:
                logging.info(
                    f"🔄 Attempting fallback PDF generation for project {project_id}"
                )
                from src.pdf_templates.attendance_record_pdf import \
                    generate_attendance_record_pdf

                pdf_file_id = await generate_attendance_record_pdf(project_id)

                logging.info(f"✅ Fallback PDF generation successful: {pdf_file_id}")

                return {
                    "status": "success",
                    "project_id": project_id,
                    "pdf_file_id": pdf_file_id,
                    "changes_detected": len(recent_records),
                    "threshold": change_threshold,
                    "message": f"Fallback method to generate PDF: {pdf_file_id}",
                }

            except Exception as fallback_error:
                logging.error(
                    f"❌ Fallback PDF generation also failed: {str(fallback_error)}"
                )
                # Don't raise here, just return error status
                return {
                    "status": "failed",
                    "project_id": project_id,
                    "error": str(fallback_error),
                    "changes_detected": len(recent_records),
                    "threshold": change_threshold,
                    "message": "Temporal.io workflow and fallback PDF generation both failed",
                }

        except Exception as e:
            logging.error(
                f"❌ Error in trigger_pdf_update_if_needed for project {project_id}: {str(e)}"
            )
            return {
                "status": "error",
                "project_id": project_id,
                "error": str(e),
                "message": "Failed to trigger PDF update",
            }

    @classmethod
    async def get_project_shift_analysis(
        cls,
        project_id: str,
        year: int,
        month: int,
    ) -> Dict[str, Any]:

        try:
            logging.info(
                f"🔍 Analyzing shift patterns for project {project_id} in {year}-{month}"
            )

            # Get date range for the month
            start_date = date(year, month, 1)
            if month == 12:
                next_month_date = date(year + 1, 1, 1)
            else:
                next_month_date = date(year, month + 1, 1)

            # Get all attendance records for the project in the specified month/year
            filters = [
                cls.project_id == project_id,
                cls.attendance_date >= start_date,
                cls.attendance_date < next_month_date,
                cls.deleted_at == None,
            ]

            attendance_records = await cls.find(*filters).to_list()

            if not attendance_records:
                logging.info(
                    f"No attendance records found for project {project_id} in {year}-{month}"
                )
                return {
                    "project_id": project_id,
                    "year": year,
                    "month": month,
                    "total_workers": 0,
                    "shift_analysis": {
                        "full_day_shifts": {
                            "unique_workers": 0,
                            "check_ins": 0,
                            "check_outs": 0,
                        }
                    },
                    "worker_details": [],
                    "daily_breakdown": {},
                }

            logging.info(
                f"Found {len(attendance_records)} attendance records for analysis"
            )

            # Get project information
            from src.models.project_model import Project

            project_info = await Project.find_one(
                Project.id == ObjectId(project_id), Project.deleted_at == None
            )

            worker_ids = set()
            for record in attendance_records:
                if record.worker_id:
                    worker_ids.add(record.worker_id)

            worker_info = {}
            for worker_id in worker_ids:
                try:
                    user = await User.find_one(
                        User.id == ObjectId(worker_id), User.deleted_at == None
                    )
                    if user:
                        worker_info[worker_id] = {
                            "payee_name": user.payee_name,
                            "mobile": user.mobile,
                        }
                except Exception as e:
                    logging.warning(
                        f"Error fetching user info for worker {worker_id}: {str(e)}"
                    )
                    worker_info[worker_id] = {
                        "payee_name": "未知",
                        "mobile": "N/A",
                    }

            # Initialize analysis counters
            shift_analysis = {
                "full_day_shifts": {
                    "unique_workers": set(),
                    "check_ins": 0,
                    "check_outs": 0,
                }
            }

            # Track daily breakdown
            daily_breakdown = {}
            worker_details = {}

            # Process each attendance record
            for record in attendance_records:
                worker_id = record.worker_id
                attendance_date = record.attendance_date
                day_key = attendance_date.day

                if day_key not in daily_breakdown:
                    daily_breakdown[day_key] = {
                        "full_day_workers": 0,
                        "total_workers": 0,
                    }

                if worker_id not in worker_details:
                    worker_details[worker_id] = {
                        "worker_info": worker_info.get(worker_id, {}),
                        "shift_counts": {
                            "full_day": 0
                        },
                        "total_days_worked": 0,
                        "days_worked": [],
                    }

                worker_details[worker_id]["total_days_worked"] += 1
                worker_details[worker_id]["days_worked"].append(day_key)

                for shift in record.shifts:
                    shift_type = shift.shift_type
                    has_checkin = shift.effective_check_in is not None
                    has_checkout = shift.effective_check_out is not None

                    # Count check-ins and check-outs
                    if has_checkin:
                        shift_analysis[f"{shift_type.value}_shifts"]["check_ins"] += 1
                        daily_breakdown[day_key][f"{shift_type.value}_check_ins"] += 1

                    if has_checkout:
                        shift_analysis[f"{shift_type.value}_shifts"]["check_outs"] += 1
                        daily_breakdown[day_key][f"{shift_type.value}_check_outs"] += 1

                    if has_checkin:
                        shift_analysis[f"{shift_type.value}_shifts"][
                            "unique_workers"
                        ].add(worker_id)
                        worker_details[worker_id]["shift_counts"][shift_type.value] += 1

                        daily_breakdown[day_key]["full_day_workers"] += 1

                # Count total workers for the day
                daily_breakdown[day_key]["total_workers"] += 1

            # Convert sets to counts and prepare final response
            for shift_type in shift_analysis:
                shift_analysis[shift_type]["unique_workers"] = len(
                    shift_analysis[shift_type]["unique_workers"]
                )

            # Prepare worker details list
            worker_details_list = []
            for worker_id, details in worker_details.items():
                worker_info = details["worker_info"]
                shift_counts = details["shift_counts"]

                worker_details_list.append(
                    {
                        "worker_id": worker_id,
                        "payee_name": worker_info.get("payee_name", "未知"),
                        "mobile": worker_info.get("mobile", "N/A"),
                        "total_days_worked": details["total_days_worked"],
                        "days_worked": sorted(details["days_worked"]),
                        "shift_counts": shift_counts,
                        "shift_summary": {
                            "full_day_shifts": shift_counts["full_day"],
                        },
                    }
                )

            # Sort worker details by payee name
            worker_details_list.sort(
                key=lambda x: x["payee_name"]
            )

            # Calculate total unique workers across all shifts
            all_workers = set()
            for shift_data in shift_analysis.values():
                if "unique_workers" in shift_data:
                    all_workers.update(shift_data.get("unique_workers", set()))

            project_title = project_info.project_title if project_info else "未知項目"

            result = {
                "project_id": project_id,
                "project_title": project_title,
                "year": year,
                "month": month,
                "total_workers": len(all_workers),
                "shift_analysis": {
                    "full_day_shifts": {
                        "unique_workers": shift_analysis["full_day_shifts"][
                            "unique_workers"
                        ],
                        "check_ins": shift_analysis["full_day_shifts"]["check_ins"],
                        "check_outs": shift_analysis["full_day_shifts"]["check_outs"],
                    },
                },
                "worker_details": worker_details_list,
                "daily_breakdown": daily_breakdown,
                "summary": {
                    "total_attendance_records": len(attendance_records),
                    "total_working_days": len(daily_breakdown),
                    "most_active_day": (
                        max(
                            daily_breakdown.keys(),
                            key=lambda k: daily_breakdown[k]["total_workers"],
                        )
                        if daily_breakdown
                        else None
                    ),
                    "least_active_day": (
                        min(
                            daily_breakdown.keys(),
                            key=lambda k: daily_breakdown[k]["total_workers"],
                        )
                        if daily_breakdown
                        else None
                    ),
                },
            }

            logging.info(f"✅ Shift analysis completed for project {project_id}")

            return result

        except Exception as e:
            logging.error(
                f"Error in get_project_shift_analysis for project {project_id}: {str(e)}"
            )
            return {
                "project_id": project_id,
                "year": year,
                "month": month,
                "error": str(e),
                "shift_analysis": {},
                "worker_details": [],
                "daily_breakdown": {},
            }

    @classmethod
    async def get_today_attendance_for_project(cls, 
                                               project_id: str, 
                                               date_input
                                               ) -> List[Dict[str, Any]]:
        try:
            from datetime import date as date_type

            if isinstance(date_input, str):
                try:
                    date_obj = datetime.strptime(date_input, "%Y-%m-%d").astimezone(HK_TZ).date()
                except ValueError:
                    logging.error(
                        f"Invalid date format: {date_input}. Expected format: YYYY-MM-DD"
                    )
                    return []
            elif isinstance(date_input, date_type):
                date_obj = date_input
            else:
                logging.error(
                    f"Invalid date type: {type(date_input)}. Expected string or date object"
                )
                return []

            logging.info(
                f"🔍 Getting today's attendance for project {project_id} on {date_obj}"
            )

            start_date = datetime.combine(date_obj, datetime.min.time()).astimezone(HK_TZ)
            end_date = datetime.combine(date_obj, datetime.max.time()).astimezone(HK_TZ)    

            logging.info(
                f"Searching for attendance records between {start_date} and {end_date}"
            )

            attendance_records = await cls.find(
                cls.project_id == project_id,
                cls.attendance_date >= start_date,
                cls.attendance_date <= end_date,
                cls.deleted_at == None,
            ).to_list()

            if not attendance_records:

                return []

            logging.info(
                f"Found {len(attendance_records)} attendance records for project {project_id} on {date_obj}"
            )

            worker_ids = set()
            for record in attendance_records:
                if record.worker_id:
                    worker_ids.add(record.worker_id)

            worker_info = {}
            for worker_id in worker_ids:
                try:
                    user = await User.find_one(
                        User.id == ObjectId(worker_id), User.deleted_at == None
                    )
                    if user:
                        worker_info[worker_id] = {
                            "worker_no": user.staff_no,
                            "payee_name": user.payee_name,
                            "english_name": user.english_name,
                            "user_waba": user.mobile,
                            "occupation": user.occupation,
                        }
                except Exception as e:
                    logging.warning(
                        f"Could not fetch user info for worker_id {worker_id}: {str(e)}"
                    )
                    worker_info[worker_id] = {
                        "worker_no": "Unknown",
                        "payee_name": "Unknown",
                        "english_name": "Unknown",
                        "user_waba": "Unknown",
                        "occupation": "",
                    }

            result = []
            for record in attendance_records:
                worker_id = record.worker_id
                user_info = worker_info.get(worker_id, {})

                shifts_data = []
                for shift in record.shifts:
                    check_in_method = None
                    check_out_method = None

                    check_in_record = next(
                        (
                            r
                            for r in shift.check_in_out_records
                            if r.check_type == CheckType.CHECK_IN
                        ),
                        None,
                    )
                    check_out_record = next(
                        (
                            r
                            for r in shift.check_in_out_records
                            if r.check_type == CheckType.CHECK_OUT
                        ),
                        None,
                    )

                    if check_in_record:
                        check_in_method = (
                            "image" if not check_in_record.attendance_method else "gps"
                        )
                    if check_out_record:
                        check_out_method = (
                            "image" if not check_out_record.attendance_method else "gps"
                        )

                    shift_info = {
                        "shift_type": shift.shift_type.value,
                        "check_in_time": (
                            shift.effective_check_in.strftime("%H:%M")
                            if shift.effective_check_in
                            else None
                        ),
                        "check_out_time": (
                            shift.effective_check_out.strftime("%H:%M")
                            if shift.effective_check_out
                            else None
                        ),
                        "check_in_method": check_in_method,
                        "check_out_method": check_out_method,
                        "is_late_check_in": shift.is_late_check_in,
                        "is_early_check_out": shift.is_early_check_out,
                        "status": (
                            "completed"
                            if shift.effective_check_in and shift.effective_check_out
                            else "pending"
                        ),
                    }
                    shifts_data.append(shift_info)

                # Calculate total working time for the day
                total_working_hours = 0
                for shift in record.shifts:
                    if shift.effective_check_in and shift.effective_check_out:
                        duration = shift.effective_check_out - shift.effective_check_in
                        total_working_hours += (
                            duration.total_seconds() / 3600
                        )  # Convert to hours

                worker_data = {
                    "worker_id": worker_id,
                    "payee_name": user_info.get(
                        "payee_name", "Unknown"
                    ),
                    "english_name": user_info.get(
                        "english_name", "Unknown"
                    ),
                    "attendance_date": record.attendance_date.isoformat(),
                    "shifts": shifts_data,
                    "total_shifts": len(record.shifts),
                    "completed_shifts": len(
                        [
                            s
                            for s in record.shifts
                            if s.effective_check_in and s.effective_check_out
                        ]
                    ),
                    "pending_shifts": len(
                        [
                            s
                            for s in record.shifts
                            if s.effective_check_in and not s.effective_check_out
                        ]
                    ),
                }

                result.append(worker_data)

            # Sort by worker number for consistent output
            result.sort(key=lambda x: x.get("payee_name", "unknown"))

            logging.info(
                f"Processed {len(result)} workers' attendance records for project {project_id}"
            )
            return result

        except Exception as e:
            logging.error(
                f"Error getting today's attendance for project {project_id}: {str(e)}"
            )
            return []


    @classmethod
    async def get_attendance_records_for_table_display(
        cls, project_id: str, year: int, month: int
    ) -> List[Dict[str, Any]]:

        try:
            logging.info(
                f"🔍 Getting attendance records for table display - Project: {project_id}, Year: {year}, Month: {month}"
            )

            # Get all attendance records for the project in the specified month/year
            start_date = date(year, month, 1)
            if month == 12:
                next_month_date = date(year + 1, 1, 1)
            else:
                next_month_date = date(year, month + 1, 1)

            filters = [
                cls.project_id == project_id,
                cls.attendance_date >= start_date,
                cls.attendance_date < next_month_date,
                cls.deleted_at == None,
            ]

            attendance_records = await cls.find(*filters).to_list()

            if not attendance_records:
                logging.info(
                    f"No attendance records found for project {project_id} in {year}-{month}"
                )
                return []

            logging.info(
                f"Found {len(attendance_records)} attendance records for table display"
            )

            # Get unique worker IDs and fetch worker information
            worker_ids = set()
            for record in attendance_records:
                if record.worker_id:
                    worker_ids.add(record.worker_id)


            worker_info = {}
            for worker_id in worker_ids:
                try:
                    user = await User.find_one(
                        User.id == ObjectId(worker_id), User.deleted_at == None
                    )
                    if user:
                        worker_info[worker_id] = {
                            "worker_no": str(user.staff_no),  # Using user ID as worker number
                            "payee_name": user.payee_name,
                            "work_type": user.work_type,
                            "occupation": user.occupation,
                            "working_hours": user.working_hours,
                            "role": user.role,
                        }
                except Exception as e:
                    logging.warning(
                        f"Error fetching user info for worker {worker_id}: {str(e)}"
                    )
                    worker_info[worker_id] = {
                        "worker_no": "Unknown",
                        "payee_name": "未知",
                        "work_type": "N/A",
                        "occupation": "N/A",
                        "working_hours": None,
                        "role": None,
                    }

            # Group records by worker
            worker_records = {}
            for record in attendance_records:
                worker_id = record.worker_id
                if worker_id not in worker_records:
                    worker_records[worker_id] = []
                worker_records[worker_id].append(record)

            # Build the final output structure grouped by work_type
            work_type_groups = {}
            for worker_id, records in worker_records.items():
                try:
                    worker_data = worker_info.get(worker_id, {})
                    work_type = worker_data.get("work_type", "N/A")

                    # Process daily records
                    start_end_times = {}
                    total_working_days = 0
                    image_attendance_dates = []  # Track dates when image-based attendance was used
                    lunch_overtime_dates = []  # Track dates when lunch overtime was used

                    for record in records:
                        # Get the day from the attendance record
                        day = record.attendance_date.day  # Extract just the day number

                        # Track lunch overtime
                        if record.lunch_overtime:
                            lunch_overtime_dates.append(record.attendance_date)

                        # Process all shifts for this day
                        shifts_data = []
                        for shift in record.shifts:
                            # Get check-in and check-out records
                            checkin_records = [
                                r
                                for r in shift.check_in_out_records
                                if r.check_type == CheckType.CHECK_IN
                            ]
                            checkout_records = [
                                r
                                for r in shift.check_in_out_records
                                if r.check_type == CheckType.CHECK_OUT
                            ]

                            # Sort records by timestamp to ensure proper pairing
                            checkin_records.sort(key=lambda r: r.timestamp)
                            checkout_records.sort(key=lambda r: r.timestamp)

                            # Create separate entries for each check-in/check-out pair
                            max_pairs = max(len(checkin_records), len(checkout_records))

                            for i in range(max_pairs):
                                shift_data = {
                                    "shift_type": shift.shift_type.value,
                                    "check_in_time": None,
                                    "check_out_time": None,
                                    "is_late_check_in": False,
                                    "is_early_check_out": False,
                                    "check_in_method": None,
                                    "check_out_method": None,
                                }

                                # Get check-in time for this pair (if available)
                                if i < len(checkin_records):
                                    checkin_record = checkin_records[i]
                                    shift_data["check_in_time"] = checkin_record.timestamp.strftime("%H:%M")
                                    shift_data["check_in_method"] = "image" if not checkin_record.attendance_method else "gps"

                                # Get check-out time for this pair (if available)
                                if i < len(checkout_records):
                                    checkout_record = checkout_records[i]
                                    shift_data["check_out_time"] = checkout_record.timestamp.strftime("%H:%M")
                                    shift_data["check_out_method"] = "image" if not checkout_record.attendance_method else "gps"

                                # Only process if we have at least one time record
                                if (
                                    shift_data["check_in_time"]
                                    or shift_data["check_out_time"]
                                ):
                                    # Check for late check-in and early check-out based on user role and working hours
                                    if shift.shift_type == ShiftType.FULL_DAY_1 or shift.shift_type == ShiftType.FULL_DAY_2 or shift.shift_type == ShiftType.FULL_DAY_3 or shift.shift_type == ShiftType.FULL_DAY_4:
                                        # Get user's role and working hours
                                        user_roles = worker_data.get("role", [])
                                        user_working_hours = worker_data.get("working_hours")
                                        
                                        is_manager = False
                                        if user_roles:
                                            for role in user_roles:
                                                role_str = str(role).lower()
                                                if any(keyword in role_str for keyword in ["manager", "director", "supervisor"]):
                                                    is_manager = True
                                                    break
                                        
                                        if is_manager:
                                            # Managers have flexible hours - never late or early
                                            if shift_data["check_in_time"]:
                                                shift_data["is_late_check_in"] = False
                                            if shift_data["check_out_time"]:
                                                shift_data["is_early_check_out"] = False
                                        elif user_working_hours:
                                            if isinstance(user_working_hours, list) and len(user_working_hours) > 0:
                                                start_time = user_working_hours[0].start_time
                                                end_time = user_working_hours[0].end_time
                                            elif hasattr(user_working_hours, 'start_time'):
                                                start_time = user_working_hours.start_time
                                                end_time = user_working_hours.end_time
                                            else:
                                                continue
                                            
                                            # Check if check-in is after start time
                                            if shift_data["check_in_time"]:
                                                checkin_time = datetime.strptime(
                                                    shift_data["check_in_time"], "%H:%M"
                                                ).time()
                                                # Convert start_time string to time object for comparison
                                                start_time_obj = datetime.strptime(
                                                    start_time, "%H:%M"
                                                ).time()
                                                shift_data["is_late_check_in"] = (
                                                    checkin_time > start_time_obj
                                                )

                                            # Check if check-out is before end time
                                            if shift_data["check_out_time"]:
                                                checkout_time = datetime.strptime(
                                                    shift_data["check_out_time"], "%H:%M"
                                                ).time()
                                                # Convert end_time string to time object for comparison
                                                end_time_obj = datetime.strptime(
                                                    end_time, "%H:%M"
                                                ).time()
                                                shift_data["is_early_check_out"] = (
                                                    checkout_time < end_time_obj
                                                )
                                        elif not is_manager and not user_working_hours:
                                            if shift_data["check_in_time"]:
                                                checkin_time = datetime.strptime(
                                                    shift_data["check_in_time"], "%H:%M"
                                                ).time()
                                                shift_data["is_late_check_in"] = (
                                                    checkin_time > time(9, 0)
                                                )

                                            if shift_data["check_out_time"]:
                                                checkout_time = datetime.strptime(
                                                    shift_data["check_out_time"], "%H:%M"
                                                ).time()
                                                shift_data["is_early_check_out"] = (
                                                    checkout_time < time(18, 0)
                                                )
                                        # For managers, no late/early checks (flexible hours)

                                    # Log late check-ins and early check-outs for debugging
                                    if (
                                        shift_data["is_late_check_in"]
                                        and shift_data["check_in_time"]
                                    ):
                                        logging.info(
                                            f"🚨 Late check-in detected: {shift_data['check_in_time']} for {shift.shift_type.value} shift (round {i+1})"
                                        )

                                    if (
                                        shift_data["is_early_check_out"]
                                        and shift_data["check_out_time"]
                                    ):
                                        logging.info(
                                            f"🚨 Early check-out detected: {shift_data['check_out_time']} for {shift.shift_type.value} shift (round {i+1})"
                                        )

                                    shifts_data.append(shift_data)

                        if shifts_data:
                            # Calculate total daily hours across all shifts (start_end_times[day]["total_daily_hours"])
                            total_daily_hours = 0
                            has_complete_shifts = False  # Track if any shift has both check-in and check-out
                            day_used_image_attendance = False  # Track if this day used image-based attendance

                            for shift_data in shifts_data:
                                if (
                                    shift_data["check_in_time"]
                                    and shift_data["check_out_time"]
                                ):
                                    # Parse times and calculate duration
                                    checkin_time = datetime.strptime(
                                        shift_data["check_in_time"], "%H:%M"
                                    ).time()
                                    checkout_time = datetime.strptime(
                                        shift_data["check_out_time"], "%H:%M"
                                    ).time()

                                    # Create datetime objects for the same day to calculate duration
                                    checkin_dt = datetime.combine(
                                        record.attendance_date, checkin_time
                                    ).replace(tzinfo=HK_TZ)
                                    checkout_dt = datetime.combine(
                                        record.attendance_date, checkout_time
                                    ).replace(tzinfo=HK_TZ)         

                                    # Handle case where checkout is next day (overnight shift)
                                    if checkout_dt < checkin_dt:
                                        checkout_dt += timedelta(days=1)

                                    duration = checkout_dt - checkin_dt
                                    total_daily_hours += duration.total_seconds() / 3600
                                    has_complete_shifts = True
                                
                                # Check if this shift used image-based attendance
                                if (shift_data.get("check_in_method") == "image" or 
                                    shift_data.get("check_out_method") == "image"):
                                    day_used_image_attendance = True

                            start_end_times[day] = {
                                "shifts": shifts_data,
                                "total_daily_hours": round(total_daily_hours, 1),
                            }

                            # Count working days: +1 if user checks in, regardless of checkout
                            if shifts_data:  # If there are any shifts (check-ins)
                                total_working_days += 1.0  # Full day for any check-in
                            
                            # Track if this day used image-based attendance
                            if day_used_image_attendance:
                                image_attendance_dates.append(record.attendance_date)

                    # Create worker record
                    worker_record = {
                        "worker_no": worker_data.get("worker_no", str(user.staff_no)),
                        "payee_name": worker_data.get("payee_name", "Unknown"),
                        "occupation": worker_data.get("occupation", "N/A"),
                        "work_type": work_type,
                        "start_end_times": start_end_times,
                        "total_working_days": total_working_days,
                        "image_attendance_dates": image_attendance_dates,
                        "lunch_overtime_dates": lunch_overtime_dates,
                    }

                    # Group by work_type
                    if work_type not in work_type_groups:
                        work_type_groups[work_type] = []
                    work_type_groups[work_type].append(worker_record)

                except Exception as e:
                    logging.error(f"Error processing worker {worker_id}: {str(e)}")
                    continue

            # Build final table data structure grouped by work_type
            table_data = []
            for work_type, workers in work_type_groups.items():
                # Sort workers within each work_type by worker number
                workers.sort(key=lambda x: x.get("worker_no", ""))
                
                work_type_group = {
                    "work_type": work_type,
                    "workers": workers,
                    "total_workers": len(workers)
                }
                table_data.append(work_type_group)

            # Sort work_type groups alphabetically
            table_data.sort(key=lambda x: x.get("work_type", ""))

            return table_data

        except Exception as e:
            logging.error(
                f"Error in get_attendance_records_for_table_display: {str(e)}"
            )
            return []

    @classmethod
    async def _create_new_attendance_record(
        cls, user_id: str, project_id: str, attendance_date: date
    ) -> "AttendanceRecord":
        """Create a new attendance record for the given date"""
        from datetime import datetime
        
        new_record = AttendanceRecord(
            worker_id=user_id,
            project_id=project_id,
            attendance_date=attendance_date,
            shifts=[],
            created_at=get_this_moment(),
            updated_at=get_this_moment(),
        )
        await new_record.save()
        logging.info(f"✅ Created new attendance record for user {user_id} on {attendance_date}")
        return new_record

    @classmethod
    async def _handle_early_morning_attendance(cls, 
                                               user_id: str, 
                                               project_id: str, 
                                               latitude: str, 
                                               longitude: str, 
                                               accuracy: str, 
                                               timestamp: datetime, 
                                               timestamp_hk_date: date,
                                               attendance_method: bool, 
                                               image_file_ids: Optional[List[str]]
                                               ) -> Tuple[Dict[str, Any], Optional["AttendanceRecord"]]:
        """Handle attendance logic for early morning (before 6 AM)"""

        previous_day = timestamp_hk_date - timedelta(days=1)
        logging.info(f"🔍 Checking previous day ({previous_day}) for pending shifts")
        
        previous_pending_record = await AttendanceRecord.find_one(
            AttendanceRecord.worker_id == user_id,
            AttendanceRecord.project_id == project_id,
            AttendanceRecord.attendance_date == previous_day,
            AttendanceRecord.deleted_at == None,
        )
        
        current_day_record = await AttendanceRecord.find_one(
            AttendanceRecord.worker_id == user_id,
            AttendanceRecord.project_id == project_id,
            AttendanceRecord.attendance_date == timestamp_hk_date,
            AttendanceRecord.deleted_at == None,
        )
        
        logging.info(f"🔍 Previous day record: {previous_pending_record is not None}")
        logging.info(f"🔍 Current day record: {current_day_record is not None}")
        
        if current_day_record is not None:
            logging.info("🔄 Processing current day record")
            action_result = await cls._determine_and_process_check_action(current_day_record, 
                                                                          latitude, 
                                                                          longitude, 
                                                                          accuracy,
                                                                          timestamp, 
                                                                          attendance_method, 
                                                                          image_file_ids
                                                                          )
            return action_result, current_day_record
        else:
            #If previous day has pending shifts, try to check out first
            if previous_pending_record is not None:
                pending_shifts = [shift for shift in previous_pending_record.shifts if shift.effective_check_in and not shift.effective_check_out]
                
                if pending_shifts:
                    logging.info(f"🔍 Found {len(pending_shifts)} pending shifts from previous day")
                
                    action_result = await cls._determine_and_process_check_action(previous_pending_record, 
                                                                                  latitude, 
                                                                                  longitude, 
                                                                                  accuracy,
                                                                                  timestamp, 
                                                                                  attendance_method, 
                                                                                  image_file_ids
                                                                                  )
                    return action_result, previous_pending_record

                else:
                    logging.info("🔄 No pending shifts found from previous day, will create new one for today")
                    attendance_record = await cls._create_new_attendance_record(user_id, 
                                                                                project_id, 
                                                                                timestamp_hk_date)

                    action_result = await cls._determine_and_process_check_action(attendance_record, 
                                                                                  latitude, 
                                                                                  longitude, 
                                                                                  accuracy,
                                                                                  timestamp, 
                                                                                  attendance_method, 
                                                                                  image_file_ids
                                                                                  )
                    return action_result, attendance_record



    @classmethod
    async def _handle_normal_attendance(cls, 
                                       user_id: str, 
                                       project_id: str, 
                                       latitude: str, 
                                       longitude: str,
                                       accuracy: str, 
                                       timestamp: datetime, 
                                       timestamp_hk_date: date,
                                       attendance_method: bool, 
                                       image_file_ids: Optional[List[str]]
                                       ) -> Tuple[Dict[str, Any], Optional["AttendanceRecord"]]:
        """Handle attendance logic for normal hours (6 AM and later)"""
        
        current_day_record = await AttendanceRecord.find_one(AttendanceRecord.worker_id == user_id,
                                                             AttendanceRecord.project_id == project_id,
                                                             AttendanceRecord.attendance_date == timestamp_hk_date,
                                                             AttendanceRecord.deleted_at == None)
        
        if current_day_record is not None:
            action_result = await cls._determine_and_process_check_action(current_day_record, 
                                                                          latitude, 
                                                                          longitude, 
                                                                          accuracy,
                                                                          timestamp, 
                                                                          attendance_method, 
                                                                          image_file_ids
                                                                          )
            return action_result, current_day_record
        else:
            logging.info("🔄 No current day record found, will create new one for today")
            attendance_record = await cls._create_new_attendance_record(user_id, 
                                                                        project_id, 
                                                                        timestamp_hk_date)

            action_result = await cls._determine_and_process_check_action(attendance_record, 
                                                                          latitude, 
                                                                         longitude, 
                                                                         accuracy,
                                                                         timestamp, 
                                                                         attendance_method, 
                                                                         image_file_ids
                                                                         )
            return action_result, attendance_record