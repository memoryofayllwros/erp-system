from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
import logging
from bson import ObjectId

from src.models.application_and_approval_model import (
    ApplicationAndApproval as ANA_MODEL,
    LeaveType,
    ApplicationStatus,
    EachApprovalStatus,
    LeaveApplicationInfo,
    ApplicationInfo
)
from src.models.user_model import User, WorkType
from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day
from src.utils.hk_holidays import is_holiday_with_sunday


class ANA_HELPERS:
    
    @classmethod
    def calculate_working_days_between(
        cls,
        start_date: date,
        end_date: date,
        work_type: WorkType = WorkType.office_ft
    ) -> float:
        """Calculate the number of working days between two dates, excluding holidays.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            work_type: Worker's work type for holiday calculation #four types of work types: office_ft, office_pt, wh, site
            
        Returns:
            Number of working days (excluding holidays)
        """
        if start_date > end_date:
            return 0
        
        working_days = 0
        current_date = start_date
        
        while current_date <= end_date:
            # Check if it's a working day (not a holiday/Sunday)
            if not is_holiday_with_sunday(
                current_date.year,
                current_date.month,
                current_date.day,
                work_type
            ):
                working_days += 1
            current_date += timedelta(days=1)
        
        return working_days

    @classmethod
    def calculate_leave_duration(
        cls,
        start_date: date,
        end_date: date,
        is_upper_half_day: Optional[bool],
        work_type: WorkType = WorkType.office_ft
    ) -> Tuple[float, float]:
        """Calculate leave duration in calendar days and working days.
        
        Args:
            start_date: Leave start date (inclusive)
            end_date: Leave end date (inclusive)
            is_upper_half_day: None for full-day leave, True for morning half-day, 
                               False for afternoon half-day
            work_type: Worker's work type for holiday calculation
            
        Returns:
            Tuple of (calendar_days, working_days)
        """
        # Validate date range
        if start_date > end_date:
            return 0.0, 0.0
        
        # Determine if this is a half-day leave
        is_half_day = is_upper_half_day is not None
        is_single_date = start_date == end_date
        
        # Helper to check if a date is a working day
        def is_working_day(d: date) -> bool:
            return not is_holiday_with_sunday(d.year, d.month, d.day, work_type)
        
        if is_half_day and not is_single_date:
            # For multi-day half-day leave, only count half-day on the end date
            # Calculate working days from start to end-1 (full days)
            days_before_end = cls.calculate_working_days_between(
                start_date, end_date - timedelta(days=1), work_type
            )
            # Add 0.5 if the end date is a working day
            working_days = days_before_end + (0.5 if is_working_day(end_date) else 0)
            calendar_days = (end_date - start_date).days + 0.5
        elif is_half_day and is_single_date:
            # Single day half-day leave
            working_days = 0.5 if is_working_day(start_date) else 0
            calendar_days = 0.5
        else:
            # Full days leave
            working_days = cls.calculate_working_days_between(
                start_date, end_date, work_type
            )
            calendar_days = (end_date - start_date).days + 1
        
        return calendar_days, working_days



    @classmethod
    async def check_advance_notice_requirement(
        cls,
        start_date: date,
        calendar_days: float,
        working_days: float,
        user_id: str
    ) -> Tuple[bool, str, int]:
        """Check if the application meets the 3-day advance notice requirement.
        
        Args:
            start_date: Leave start date
            calendar_days: Total calendar days of leave
            working_days: Total working days of leave
            user_id: User ID to get work type
            
        Returns:
            Tuple of (is_policy_breach, breach_message, working_days_before_leave)
        """
        today = get_this_day()
        
        # Get user's work type
        user = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)
        work_type = user.work_type if user else WorkType.office_ft
        
        # Calculate working days from today to leave start (exclusive)
        if start_date <= today:
            working_days_notice = 0
        else:
            working_days_notice = cls.calculate_working_days_between(
                today + timedelta(days=1),  # Start from tomorrow
                start_date - timedelta(days=1),  # Up to day before leave
                work_type
            )
        
        # Policy: Leave > 1 day requires 3 working days advance notice
        requires_advance = working_days > 1
        has_sufficient_notice = working_days_notice >= 3
        
        is_breach = requires_advance and not has_sufficient_notice
        
        breach_message = ""
        if is_breach:
            breach_message = (
                f"⚠️ Leave Policy Notice: Your leave period is {working_days:.1f} working days, "
                f"which requires 3 working days advance notice. You are applying with only "
                f"{working_days_notice} working day(s) notice. While your application can still be "
                f"submitted, it may require special approval or justification."
            )
        
        return is_breach, breach_message, working_days_notice

    @classmethod
    async def is_date_conflict_with_other_applications(
        cls,
        new_start_date: date,
        new_end_date: date,
        is_half_day: bool,
        is_upper_half_day: Optional[bool],
        user_id: str,
        exclude_application_code: Optional[str] = None
    ) -> Tuple[bool, Optional[ANA_MODEL]]:
        """Check if the new start date and end date conflicts with other applications.
        
        Conflict rules:
        - Full day conflicts with any leave on overlapping dates
        - Half day conflicts with full day on the same date
        - Half day conflicts with half day on the same date ONLY if same half (both morning or both afternoon)
        """
        try:
            query = ANA_MODEL.find(
                ANA_MODEL.user_id == user_id,
                ANA_MODEL.deleted_at == None
            )
            
            if exclude_application_code:
                query = query.find(ANA_MODEL.application_code != exclude_application_code)
            
            user_existing_applications = await query.to_list()
            
            for application in user_existing_applications:
                if not application.application_info or not application.application_info.leave_application_info:
                    continue
                    
                existing_info = application.application_info.leave_application_info
                existing_start = existing_info.start_date
                existing_end = existing_info.end_date
                existing_is_half_day = existing_info.is_half_day
                existing_is_upper_half_day = existing_info.is_upper_half_day
                
                # Check if date ranges overlap at all
                if not (new_start_date <= existing_end and existing_start <= new_end_date):
                    continue
                
                # Case 1: Both are full-day leaves
                if not is_half_day and not existing_is_half_day:
                    # Overlapping date ranges conflict
                    return True, application
                
                # Case 2: New is full-day, existing is half-day
                if not is_half_day and existing_is_half_day:
                    # A full day conflicts with a half day on the same date
                    if existing_start >= new_start_date and existing_start <= new_end_date:
                        return True, application
                
                # Case 3: New is half-day, existing is full-day
                if is_half_day and not existing_is_half_day:
                    # A half day conflicts with a full day on the same date
                    if new_start_date >= existing_start and new_start_date <= existing_end:
                        return True, application
                
                # Case 4: Both are half-days on the same date
                if is_half_day and existing_is_half_day and new_start_date == existing_start:
                    # Only conflict if same half (both morning or both afternoon)
                    # Note: is_upper_half_day and existing_is_upper_half_day are None for full days,
                    # so we compare them only when both are half days
                    if is_upper_half_day == existing_is_upper_half_day:
                        return True, application
                    # Different halves (morning vs afternoon) don't conflict
            
            return False, None

        except Exception as e:
            logging.error(f"Failed to check date conflict: {str(e)}")
            return True, None

    @classmethod
    async def is_sequencing_with_other_applications(
        cls,
        new_start_date: date,
        new_end_date: date,
        is_half_day: bool,
        is_upper_half_day: Optional[bool],
        user_id: str,
    ) -> Tuple[bool, Optional[float]]:
        """Check if the new application is adjacent to existing applications."""
        try:
            query = ANA_MODEL.find(
                ANA_MODEL.user_id == user_id,
                ANA_MODEL.deleted_at == None
            )
            
            user_existing_applications = await query.to_list()
            
            all_leaves = []
            
            all_leaves.append({
                'start': new_start_date,
                'end': new_end_date,
                'is_half_day': is_half_day,
                'is_upper_half': is_upper_half_day,
                'days': 0.5 if is_half_day else (new_end_date - new_start_date).days + 1
            })
            
            for application in user_existing_applications:
                if not application.application_info or not application.application_info.leave_application_info:
                    continue
                    
                leave_info = application.application_info.leave_application_info
                total_days = 0.5 if leave_info.is_half_day else (leave_info.end_date - leave_info.start_date).days + 1
                all_leaves.append({
                    'start': leave_info.start_date,
                    'end': leave_info.end_date,
                    'is_half_day': leave_info.is_half_day,
                    'is_upper_half': leave_info.is_upper_half_day,
                    'days': total_days
                })
            
            all_leaves.sort(key=lambda x: (x['start'], not x['is_upper_half']))
            
            merged_sequences = []
            current_start = all_leaves[0]['start']
            current_end = all_leaves[0]['end']
            current_total_days = all_leaves[0]['days']
            contains_new_leave = True
            
            for i in range(1, len(all_leaves)):
                leave = all_leaves[i]
                
                is_adjacent = False
                
                if current_end == leave['start']:
                    is_adjacent = True
                elif current_end == leave['start'] - timedelta(days=1):
                    is_adjacent = True
                elif current_end >= leave['start']:
                    is_adjacent = True
                
                if is_adjacent:
                    current_end = max(current_end, leave['end'])
                    current_total_days += leave['days']
                else:
                    merged_sequences.append({
                        'start': current_start,
                        'end': current_end,
                        'total_days': current_total_days,
                        'contains_new': contains_new_leave
                    })
                    current_start = leave['start']
                    current_end = leave['end']
                    current_total_days = leave['days']
                    contains_new_leave = False
            
            merged_sequences.append({
                'start': current_start,
                'end': current_end,
                'total_days': current_total_days,
                'contains_new': contains_new_leave
            })
            
            for sequence in merged_sequences:
                if sequence['contains_new'] and sequence['total_days'] > 1:
                    return True, sequence['total_days']
            
            return False, None

        except Exception as e:
            logging.error(f"Failed to check sequencing: {str(e)}")
            return False, None

    @classmethod
    async def add_leave_application_function(
        cls,
        user_id: str,
        start_date: date,
        end_date: date,
        leave_type: str,
        is_half_day: bool,
        is_upper_half_day: Optional[bool] = None,
        project_id: Optional[str] = None,
        leave_reason: Optional[str] = None,
        medical_certificate: Optional[str] = None,
    ) -> dict:

        policy_notices = []
        
        try:
            # 1. Validate basic inputs
            if not user_id:
                raise ValueError("User ID is required")
                
            if start_date > end_date:
                raise ValueError("Start date cannot be after end date")

            # 2. Validate leave type
            try:
                leave_type_enum = LeaveType(leave_type.lower())
            except ValueError:
                valid_types = ', '.join([lt.value for lt in LeaveType])
                raise ValueError(f"Invalid leave type: '{leave_type}'. Must be one of: {valid_types}")

            # 3. Get user information
            user = await User.find_one(User.id == ObjectId(user_id), User.deleted_at == None)
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            
            work_type = user.work_type if hasattr(user, 'work_type') else WorkType.office_ft

            # 4. Calculate leave duration (calendar days and working days)
            calendar_days, working_days = cls.calculate_leave_duration(
                start_date, end_date, is_upper_half_day if is_half_day else None, work_type
            )
            
            logging.info(
                f"Leave duration calculated: {calendar_days} calendar days, "
                f"{working_days} working days for user {user_id}"
            )

            # 5. Check advance notice requirement and policy breach
            is_policy_breach, breach_message, working_days_notice = await cls.check_advance_notice_requirement(
                start_date, calendar_days, working_days, user_id
            )
            
            if breach_message:
                policy_notices.append(breach_message)
                
            # Additional policy check: Leave longer than 1 day should be applied 3 days before
            today = get_this_day()
            days_before_start = (start_date - today).days
            
            if working_days > 1 and days_before_start < 3:
                is_policy_breach = True
                advance_notice = (
                    "⚠️ Leave Policy Notice: Leave periods longer than 1 day should be applied "
                    "at least 3 days before the start date. Your application has been marked as "
                    "a policy breach and may require special approval."
                )
                policy_notices.append(advance_notice)

            # 6. Validate medical certificate for sick leave
            if leave_type_enum == LeaveType.SICK_LEAVE:
                if working_days > 1 and not medical_certificate:
                    medical_cert_notice = (
                        "⚠️ Medical certificate is required for sick leave longer than 1 working day. "
                        "Please upload it after your leave period."
                    )
                    policy_notices.append(medical_cert_notice)

            # 7. Check for date conflicts
            has_conflict, conflicting_app = await cls.is_date_conflict_with_other_applications(
                start_date, end_date, is_half_day, is_upper_half_day, user_id
            )
            
            if has_conflict:
                if conflicting_app and conflicting_app.application_info:
                    conflict_info = conflicting_app.application_info.leave_application_info
                    if conflict_info:
                        # Build the conflict period string
                        if conflict_info.start_date == conflict_info.end_date:
                            if conflict_info.is_half_day:
                                half_day_str = " (morning)" if conflict_info.is_upper_half_day else " (afternoon)"
                                conflict_period = f"{conflict_info.start_date}{half_day_str}"
                            else:
                                conflict_period = f"{conflict_info.start_date}"
                        else:
                            conflict_period = f"{conflict_info.start_date} to {conflict_info.end_date}"
                        
                        # Add half-day info for new application
                        if is_half_day:
                            new_half_str = " (morning)" if is_upper_half_day else " (afternoon)"
                        else:
                            new_half_str = ""
                        
                        raise ValueError(
                            f"Date conflict with existing application {conflicting_app.application_code} "
                            f"({conflict_period}). Your requested period ({start_date}{new_half_str}) overlaps with "
                            f"an existing leave. Please choose different dates."
                        )
                raise ValueError("Date conflict with existing application. Please choose different dates.")

            # 8. Check for sequencing with other applications
            is_sequencing, total_sequence_days = await cls.is_sequencing_with_other_applications(
                start_date, end_date, is_half_day, is_upper_half_day, user_id
            )
            
            if is_sequencing and total_sequence_days:
                sequence_message = (
                    f"📋 This application connects with existing leave(s) to form a continuous "
                    f"period of {total_sequence_days:.1f} calendar days. Combined leave periods "
                    f"exceeding 1 day require ex-ante approval."
                )
                policy_notices.append(sequence_message)
                logging.info(
                    f"Application for user {user_id} is part of sequence: {total_sequence_days} days"
                )

            # 9. Find approvers
            approvers = await User._find_approvers(user_id)
            if not approvers:
                raise ValueError(
                    "No approvers found for your application. Please contact your administrator."
                )
            
            logging.info(f"Found {len(approvers)} approver(s) for user {user_id}")

            # 10. Generate application code
            application_code = await ANA_MODEL._get_application_code()
            if not application_code:
                raise RuntimeError("Failed to generate application code. Please try again.")

            # 11. Determine if ex-ante approval is required
            requires_ex_ante = working_days > 1 or (
                is_sequencing and total_sequence_days and total_sequence_days > 1
            )
            
            approval_status_list = [
                EachApprovalStatus(
                    approver_id=str(approver),
                    approval_status=ApplicationStatus.PENDING,
                    approval_timestamp=get_this_moment()
                )
                for approver in approvers
            ]

            # 12. Create leave application info
            leave_info = LeaveApplicationInfo(
                start_date=start_date,
                end_date=end_date,
                is_half_day=is_half_day,
                is_upper_half_day=is_upper_half_day,
                leave_reason=leave_reason,
                certificate_file_ids=[medical_certificate] if medical_certificate else None
            )

            # 13. Create application info
            application_info = ApplicationInfo(
                leave_application_info=leave_info
            )

            # 14. Create and save the application
            application = ANA_MODEL(
                application_code=application_code,
                user_id=user_id,
                project_id=project_id or None,
                application_type=leave_type_enum,
                application_info=application_info,
                approval_status=approval_status_list,
                leave_policy_breach=is_policy_breach,
                created_at=get_this_moment()
            )

            await application.save()
            
            # 15. Build success message based on approval requirement
            if requires_ex_ante:
                approval_message = (
                    f"✅ Your leave application has been submitted successfully with code {application_code}. "
                    f"Since your leave exceeds 1 working day, it requires ex-ante approval. Your approvers have been "
                    f"notified and will respond within 3 working days."
                )
            else:
                approval_message = (
                    f"✅ Your leave application has been submitted successfully with code {application_code}. "
                    f"You can take this leave directly. Your manager will review and approve it during the "
                    f"month-end batch processing."
                )
            
            # 16. Log success
            logging.info(
                f"✅ Created leave application {application_code} for user {user_id}: "
                f"{leave_type_enum.value} from {start_date} to {end_date} "
                f"({calendar_days} calendar days, {working_days} working days, "
                f"ex-ante required: {requires_ex_ante}, policy breach: {is_policy_breach})"
            )
            
            # 17. Return comprehensive response
            return {
                'status': 'success',
                'message': approval_message,
                'application': application,
                'policy_notices': policy_notices,
                'details': {
                    'application_code': application_code,
                    'calendar_days': calendar_days,
                    'working_days': working_days,
                    'requires_ex_ante': requires_ex_ante,
                    'is_policy_breach': is_policy_breach,
                    'working_days_notice': working_days_notice,
                    'is_sequencing': is_sequencing,
                    'total_sequence_days': total_sequence_days
                }
            }
            
        except ValueError as e:
            logging.warning(f"Validation error creating leave application: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'policy_notices': policy_notices,
                'details': {}
            }
        except RuntimeError as e:
            logging.error(f"Runtime error creating leave application: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'policy_notices': policy_notices,
                'details': {}
            }
        except Exception as e:
            logging.error(
                f"Unexpected error creating leave application for user {user_id}: {str(e)}", 
                exc_info=True
            )
            return {
                'status': 'error',
                'message': f"Failed to create leave application: {str(e)}",
                'policy_notices': policy_notices,
                'details': {}
            }