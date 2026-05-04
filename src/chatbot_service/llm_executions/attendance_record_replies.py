import logging
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId

from src.models.project_model import Project
from src.pdf_templates.attendance_record_pdf import \
    generate_attendance_record_pdf

logger = logging.getLogger(__name__)
from src.models.user_model import User
from src.utils.datetime_standarization_helpers import get_this_moment

async def regenerate_all_attendance_pdfs(force: bool = True) -> Dict[str, Any]:
    """
    Regenerate attendance record PDF for all projects

    Args:
        user_id: The user ID requesting the regeneration
        force: If True, always regenerate PDFs regardless of recent generation timestamps
    """
    try:
        logging.info(f"🔄 Starting PDF regeneration")

        projects = await Project.find(Project.deleted_at == None).to_list()
        logging.info(f"Projects length: {len(projects)}")

        results = []
        success_count = 0
        skipped_count = 0

        for project in projects:
            project_id = str(project.id)
            try:
                result = await regenerate_one_attendance_pdf(project_id)
                results.append(result)

                # Count based on status
                if result.get("status") == "success":
                    success_count += 1
                elif result.get("status") == "skipped":
                    skipped_count += 1

            except Exception as project_error:
                error_msg = str(project_error)
                logger.warning(f"⚠️ PDF regeneration failed (non-critical): {error_msg}")
                # Check if it's a table sizing error
                if "too large" in error_msg or "Flowable" in error_msg:
                    logger.error(
                        f"📊 Table sizing error detected for project {project_id}. This may be due to too many columns or insufficient space."
                    )
                    logger.error(
                        f"🔧 Consider: reducing font sizes, adjusting margins, or splitting data across multiple pages."
                    )

                # Continue with other projects even if one fails
                continue

        # Get updated project data after regeneration
        updated_projects = await Project.find(Project.deleted_at == None).to_list()

        return {
            "status": "success",
            "message": f"Successfully regenerated {success_count} of {len(projects)} attendance PDFs, skipped {skipped_count} projects with no attendance records",
            "results": results,
            "summary": {
                "total_projects": len(projects),
                "successful": success_count,
                "skipped": skipped_count,
                "failed": len(projects) - success_count - skipped_count,
            },
            "updated_projects": updated_projects,
        }

    except Exception as e:
        logger.error(f"❌ Error regenerating all attendance PDFs: {str(e)}")
        raise


async def regenerate_one_attendance_pdf(project_id: str) -> Dict[str, Any]:

    try:
        logger.info(f"🔄 Regenerating attendance PDF for project {project_id}")

        # Generate new PDF
        pdf_file_id = await generate_attendance_record_pdf(project_id)

        # Handle case where no attendance records exist
        if pdf_file_id is None:
            logger.warning(
                f"⚠️ No attendance records found for project {project_id}, skipping PDF generation"
            )
            return {
                "status": "skipped",
                "project_id": project_id,
                "message": "No attendance records found for this project",
                "generated_at": get_this_moment().isoformat(),
            }

        # Update project with new PDF ID and timestamp using the Project model method
        logging.info(f"PDF File ID: {pdf_file_id}")
        
        # Use the Project model's update_attendance_record_id method for consistency
        update_result = await Project.update_attendance_record_id(
            project_id=project_id,
            attendance_record_id=pdf_file_id
        )
        
        if update_result.get("status") == "success":
            logger.info(
                f"✅ Successfully updated attendance_record_id for project {project_id}: {pdf_file_id}"
            )
        else:
            logger.error(
                f"❌ Failed to update attendance_record_id: {update_result.get('message', 'Unknown error')}"
            )
            # Continue with the process even if update fails

        logger.info(
            f"✅ Successfully regenerated attendance PDF for project {project_id}: {pdf_file_id}"
        )

        return {
            "status": "success",
            "pdf_file_id": pdf_file_id,
            "project_id": project_id,
            "generated_at": get_this_moment().isoformat(),
            "message": "Attendance PDF regenerated successfully",
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"❌ Error regenerating attendance PDF for project {project_id}: {error_msg}"
        )

        # Provide more specific error information for table sizing issues
        if "too large" in error_msg or "Flowable" in error_msg:
            logger.error(
                f"📊 This is a table sizing issue. The table has too many columns or insufficient space."
            )
            logger.error(f"🔧 Technical details: {error_msg}")
            logger.error(
                f"💡 Solutions: Reduce font sizes, adjust margins, or split data across multiple pages."
            )

        raise
