"""
Temporal Activities for Attendance Management
Activities perform the actual work for attendance record operations
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from bson import ObjectId

from src.chatbot_service.llm_executions.attendance_record_replies import \
    regenerate_all_attendance_pdfs
from src.models.attendance_record_model import AttendanceRecord
from src.models.project_model import Project

logger = logging.getLogger(__name__)


async def detect_attendance_changes(project_id: str) -> Dict[str, Any]:

    try:
        # Get project info
        project = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        if not project:
            return {
                "changes_detected": False,
                "change_count": 0,
                "message": "Project not found",
            }

        # Check last PDF generation time
        last_pdf_time = getattr(project, "last_attendance_pdf_generated", None)

        # Get recent attendance records
        recent_records = await AttendanceRecord.find(
            AttendanceRecord.project_id == project_id,
            AttendanceRecord.deleted_at == None,
            AttendanceRecord.updated_at >= (get_this_moment() - timedelta(days=7)),
        ).to_list()

        if not recent_records:
            return {
                "changes_detected": False,
                "change_count": 0,
                "message": "No recent attendance records found",
            }

        # Count changes since last PDF generation
        change_count = 0
        if last_pdf_time:
            for record in recent_records:
                if record.updated_at > last_pdf_time:
                    change_count += 1
        else:
            # No previous PDF, count all recent records
            change_count = len(recent_records)

        changes_detected = change_count > 0

        return {
            "changes_detected": changes_detected,
            "change_count": change_count,
            "last_pdf_time": last_pdf_time.isoformat() if last_pdf_time else None,
            "recent_records_count": len(recent_records),
            "project_code": project.project_code,
            "message": f"Detected {change_count} changes since last PDF generation",
        }

    except Exception as e:
        logger.error(
            f"Error detecting attendance changes for project {project_id}: {str(e)}"
        )
        raise


async def cleanup_old_attendance_records(maintenance_type: str) -> Dict[str, Any]:
    """
    Clean up old attendance records based on maintenance type

    Args:
        maintenance_type: Type of maintenance (daily, weekly, monthly)

    Returns:
        Dict with cleanup results
    """
    try:
        logger.info(f"🧹 Starting attendance record cleanup: {maintenance_type}")

        # Define retention periods
        retention_periods = {
            "daily": timedelta(days=1),  # Keep 1 day
            "weekly": timedelta(weeks=1),  # Keep 1 week
            "monthly": timedelta(days=30),  # Keep 30 days
        }

        retention_period = retention_periods.get(maintenance_type, timedelta(days=30))
        cutoff_date = get_this_moment() - retention_period

        # Find old records
        old_records = await AttendanceRecord.find(
            AttendanceRecord.created_at < cutoff_date,
            AttendanceRecord.deleted_at == None,
        ).to_list()

        if not old_records:
            return {
                "status": "no_cleanup_needed",
                "maintenance_type": maintenance_type,
                "records_processed": 0,
                "message": f"No records older than {retention_period.days} days found",
            }

        # Soft delete old records
        deleted_count = 0
        for record in old_records:
            try:
                record.deleted_at = get_this_moment()
                await record.save()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting record {record.id}: {str(e)}")
                continue

        logger.info(f"✅ Cleaned up {deleted_count} old attendance records")

        return {
            "status": "success",
            "maintenance_type": maintenance_type,
            "records_processed": len(old_records),
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "message": f"Successfully cleaned up {deleted_count} old attendance records",
        }

    except Exception as e:
        logger.error(f"❌ Error during attendance record cleanup: {str(e)}")
        raise


async def validate_attendance_data_integrity(maintenance_type: str) -> Dict[str, Any]:
    """
    Validate integrity of attendance data

    Args:
        maintenance_type: Type of maintenance (daily, weekly, monthly)

    Returns:
        Dict with validation results
    """
    try:
        logger.info(f"🔍 Validating attendance data integrity: {maintenance_type}")

        validation_results = {
            "status": "success",
            "maintenance_type": maintenance_type,
            "checks_performed": [],
            "issues_found": [],
            "timestamp": get_this_moment().isoformat(),
        }

        # Check 1: Orphaned records (no valid project)
        orphaned_records = await AttendanceRecord.find(
            AttendanceRecord.deleted_at == None
        ).to_list()

        orphaned_count = 0
        for record in orphaned_records:
            try:
                project = await Project.find_one(
                    Project.id == ObjectId(record.project_id)
                )
                if not project or project.deleted_at:
                    orphaned_count += 1
            except Exception:
                orphaned_count += 1

        if orphaned_count > 0:
            validation_results["issues_found"].append(
                {
                    "type": "orphaned_records",
                    "count": orphaned_count,
                    "severity": "medium",
                }
            )

        validation_results["checks_performed"].append("orphaned_records_check")

        # Check 2: Invalid shift configurations
        invalid_shifts = 0
        for record in orphaned_records:
            for shift in record.shifts:
                if not shift.shift_type or not hasattr(shift, "check_in_out_records"):
                    invalid_shifts += 1

        if invalid_shifts > 0:
            validation_results["issues_found"].append(
                {
                    "type": "invalid_shift_configurations",
                    "count": invalid_shifts,
                    "severity": "low",
                }
            )

        validation_results["checks_performed"].append("shift_configuration_check")

        # Check 3: Timestamp consistency
        timestamp_issues = 0
        for record in orphaned_records:
            for shift in record.shifts:
                for check_record in shift.check_in_out_records:
                    if (
                        not check_record.timestamp
                        or check_record.timestamp > get_this_moment()
                    ):
                        timestamp_issues += 1

        if timestamp_issues > 0:
            validation_results["issues_found"].append(
                {
                    "type": "timestamp_inconsistencies",
                    "count": timestamp_issues,
                    "severity": "high",
                }
            )

        validation_results["checks_performed"].append("timestamp_consistency_check")

        # Update overall status if issues found
        if validation_results["issues_found"]:
            validation_results["status"] = "issues_found"

        logger.info(
            f"✅ Data integrity validation completed: {len(validation_results['issues_found'])} issues found"
        )

        return validation_results

    except Exception as e:
        logger.error(f"❌ Error during data integrity validation: {str(e)}")
        raise


async def batch_regenerate_project_pdfs(project_ids: List[str]) -> Dict[str, Any]:

    try:
        logger.info(
            f"🔄 Starting batch PDF regeneration for {len(project_ids)} projects"
        )

        results = []
        errors = []

        # Process projects in parallel with semaphore to limit concurrency
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent PDF generations

        async def process_single_project(project_id: str):
            async with semaphore:
                try:
                    result = await regenerate_all_attendance_pdfs()
                    return {
                        "project_id": project_id,
                        "status": "success",
                        "result": result,
                    }
                except Exception as e:
                    return {
                        "project_id": project_id,
                        "status": "error",
                        "error": str(e),
                    }

        # Create tasks for all projects
        tasks = [process_single_project(project_id) for project_id in project_ids]

        # Execute all tasks
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in batch_results:
            if isinstance(result, Exception):
                errors.append({"project_id": "unknown", "error": str(result)})
            elif result["status"] == "success":
                results.append(result)
            else:
                errors.append(result)

        logger.info(
            f"✅ Batch PDF regeneration completed: {len(results)} successful, {len(errors)} failed"
        )

        return {
            "status": "completed",
            "total_projects": len(project_ids),
            "successful": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
            "timestamp": get_this_moment().isoformat(),
        }

    except Exception as e:
        logger.error(f"❌ Error during batch PDF regeneration: {str(e)}")
        raise
