"""
Temporal Workflows for Attendance Management
Workflows orchestrate activities and handle business logic for attendance records
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from src.utils.datetime_standarization_helpers import get_this_moment
# Import activities directly
from temporal_app.activities.attendance_activities import (
    cleanup_old_attendance_records, detect_attendance_changes,
    regenerate_all_attendance_pdfs, validate_attendance_data_integrity)


@workflow.defn
class AttendancePDFUpdateWorkflow:

    @workflow.run
    async def run(
        self, project_id: str, force_regenerate: bool = False
    ) -> Dict[str, Any]:

        try:
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=5),
                maximum_attempts=3,
                backoff_coefficient=2.0,
            )

            # Step 1: Detect attendance changes
            changes_detected = await workflow.execute_activity(
                detect_attendance_changes,
                project_id,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

            if not changes_detected and not force_regenerate:
                workflow.logger.info(
                    f"No attendance changes detected for project {project_id}"
                )
                return {
                    "status": "no_changes",
                    "project_id": project_id,
                    "message": "No attendance changes detected, PDF remains current",
                }

            # Step 2: Regenerate attendance PDF
            workflow.logger.info(
                f"🔄 Starting PDF regeneration for project {project_id}"
            )
            pdf_result = await workflow.execute_activity(
                regenerate_all_attendance_pdfs,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=retry_policy,
            )

            workflow.logger.info(
                f"✅ Attendance PDF updated for project {project_id}: {pdf_result}"
            )

            # Verify the result
            if pdf_result.get("status") != "success":
                workflow.logger.warning(
                    f"⚠️ PDF regeneration returned non-success status: {pdf_result}"
                )

            return {
                "status": "success",
                "project_id": project_id,
                "pdf_result": pdf_result,
                "changes_detected": changes_detected,
                "workflow_completed_at": get_this_moment().isoformat(),
            }

        except Exception as e:
            workflow.logger.error(
                f"❌ Error in AttendancePDFUpdateWorkflow for project {project_id}: {str(e)}"
            )
            workflow.logger.error(f"📋 Error details: {type(e).__name__}: {str(e)}")

            # Return error result instead of raising
            return {
                "status": "error",
                "project_id": project_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "workflow_failed_at": get_this_moment().isoformat(),
                "message": f"Workflow failed: {str(e)}",
            }


@workflow.defn
class BatchAttendancePDFUpdateWorkflow:

    @workflow.run
    async def run(
        self, project_ids: List[str], force_regenerate: bool = False
    ) -> Dict[str, Any]:

        try:
            results = []
            errors = []

            for project_id in project_ids:
                try:
                    # Execute individual project update
                    result = await workflow.execute_activity(
                        regenerate_all_attendance_pdfs,
                        start_to_close_timeout=timedelta(minutes=15),
                    )
                    results.append(
                        {
                            "project_id": project_id,
                            "status": "success",
                            "result": result,
                        }
                    )
                except Exception as e:
                    errors.append({"project_id": project_id, "error": str(e)})
                    workflow.logger.error(
                        f"Failed to update project {project_id}: {str(e)}"
                    )

            return {
                "status": "completed",
                "total_projects": len(project_ids),
                "successful": len(results),
                "failed": len(errors),
                "results": results,
                "errors": errors,
            }

        except Exception as e:
            workflow.logger.error(
                f"Error in BatchAttendancePDFUpdateWorkflow: {str(e)}"
            )
            raise


@workflow.defn
class ScheduledAttendanceMaintenanceWorkflow:

    @workflow.run
    async def run(self, maintenance_type: str = "daily") -> Dict[str, Any]:

        try:
            results = {}

            # Step 1: Validate data integrity
            if maintenance_type in ["daily", "weekly"]:
                integrity_result = await workflow.execute_activity(
                    validate_attendance_data_integrity,
                    maintenance_type,
                    start_to_close_timeout=timedelta(minutes=10),
                )
                results["data_integrity"] = integrity_result

            # Step 2: Clean up old records (weekly/monthly)
            if maintenance_type in ["weekly", "monthly"]:
                cleanup_result = await workflow.execute_activity(
                    cleanup_old_attendance_records,
                    maintenance_type,
                    start_to_close_timeout=timedelta(minutes=15),
                )
                results["cleanup"] = cleanup_result

            # Step 3: Regenerate outdated PDFs (monthly)
            if maintenance_type == "monthly":
                # Get projects that need PDF updates
                from src.models.project_model import Project

                projects = await Project.find(Project.deleted_at == None).to_list()

                pdf_results = []
                for project in projects[:10]:  # Limit to 10 projects per run
                    try:
                        pdf_result = await workflow.execute_activity(
                            regenerate_all_attendance_pdfs,
                            str(project.id),
                            start_to_close_timeout=timedelta(minutes=10),
                        )
                        pdf_results.append(
                            {
                                "project_id": str(project.id),
                                "project_code": project.project_code,
                                "result": pdf_result,
                            }
                        )
                    except Exception as e:
                        pdf_results.append(
                            {
                                "project_id": str(project.id),
                                "project_code": project.project_code,
                                "error": str(e),
                            }
                        )

                results["pdf_updates"] = pdf_results

            workflow.logger.info(
                f"Scheduled maintenance {maintenance_type} completed: {results}"
            )
            return {
                "status": "success",
                "maintenance_type": maintenance_type,
                "results": results,
                "timestamp": get_this_moment().isoformat(),
            }

        except Exception as e:
            workflow.logger.error(
                f"Error in ScheduledAttendanceMaintenanceWorkflow: {str(e)}"
            )
            raise


@workflow.defn
class AttendanceChangeDetectionWorkflow:

    @workflow.run
    async def run(self, project_id: str, change_threshold: int = 1) -> Dict[str, Any]:

        try:
            # Step 1: Detect changes
            changes = await workflow.execute_activity(
                detect_attendance_changes,
                project_id,
                start_to_close_timeout=timedelta(minutes=5),
            )

            if not changes:
                return {
                    "status": "no_changes",
                    "project_id": project_id,
                    "message": "No attendance changes detected",
                }

            # Step 2: Check if changes meet threshold
            change_count = changes.get("change_count", 0)
            if change_count < change_threshold:
                return {
                    "status": "below_threshold",
                    "project_id": project_id,
                    "change_count": change_count,
                    "threshold": change_threshold,
                    "message": f"Changes ({change_count}) below threshold ({change_threshold})",
                }

            # Step 3: Trigger PDF update
            pdf_result = await workflow.execute_activity(
                regenerate_attendance_pdfs,
                project_id,
                start_to_close_timeout=timedelta(minutes=15),
            )

            return {
                "status": "threshold_exceeded",
                "project_id": project_id,
                "change_count": change_count,
                "threshold": change_threshold,
                "pdf_result": pdf_result,
                "message": f"PDF updated due to {change_count} changes exceeding threshold {change_threshold}",
            }

        except Exception as e:
            workflow.logger.error(
                f"Error in AttendanceChangeDetectionWorkflow: {str(e)}"
            )
            raise


"""
Logical Flow:

No changes → Exit early (no mode matters)
Changes detected → Apply mode-specific threshold
If changes ≥ effective_threshold → Trigger PDF update
If changes < effective_threshold → Return below_threshold status



So yes, you're correct: when len(changes) == 0, there's no need to trigger any processing, including critical mode, because there's simply nothing to process. The workflow will exit early and save resources.


@workflow.defn
class AttendanceChangeDetectionWorkflow:
    @workflow.run
    async def run(self, project_id: str, change_threshold: int = 1, trigger_mode: str = "auto") -> Dict[str, Any]:
        
        #Detect significant attendance changes and trigger updates
        
        #Args:
            #project_id: Project to monitor
            #change_threshold: Minimum number of changes to trigger update
            #trigger_mode: "auto", "critical", or "batch"
        
        try:
            # Step 1: Detect changes
            changes = await workflow.execute_activity(
                detect_attendance_changes,
                project_id,
                start_to_close_timeout=timedelta(minutes=5)
            )
            
            # Step 2: Early return if no changes detected
            if not changes or len(changes) == 0:
                return {
                    "status": "no_changes",
                    "project_id": project_id,
                    "trigger_mode": trigger_mode,
                    "message": "No attendance changes detected - no action needed regardless of mode"
                }
            
            # Step 3: Determine effective threshold based on trigger mode
            if trigger_mode == "critical":
                effective_threshold = 1  # Immediate update for critical changes
            elif trigger_mode == "batch":
                effective_threshold = max(change_threshold, 5)  # Wait for multiple changes
            else:  # "auto" mode
                effective_threshold = change_threshold
            
            # Step 4: Check if changes meet the effective threshold
            change_count = len(changes)  # or changes.get("change_count", 0) if changes is a dict
            
            if change_count < effective_threshold:
                return {
                    "status": "below_threshold",
                    "project_id": project_id,
                    "change_count": change_count,
                    "effective_threshold": effective_threshold,
                    "trigger_mode": trigger_mode,
                    "message": f"Changes ({change_count}) below effective threshold ({effective_threshold}) for {trigger_mode} mode"
                }
            
            # Step 5: Trigger PDF update (only if threshold is met)
            pdf_result = await workflow.execute_activity(
                regenerate_attendance_pdfs,
                project_id,
                start_to_close_timeout=timedelta(minutes=15)
            )
            
            return {
                "status": "threshold_exceeded",
                "project_id": project_id,
                "change_count": change_count,
                "effective_threshold": effective_threshold,
                "trigger_mode": trigger_mode,
                "pdf_result": pdf_result,
                "message": f"PDF updated: {change_count} changes exceeded threshold ({effective_threshold}) in {trigger_mode} mode"
            }
            
        except Exception as e:
            workflow.logger.error(f"Error in AttendanceChangeDetectionWorkflow: {str(e)}")
            raise
"""
