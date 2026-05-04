import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from src.models.project_model import Project
from src.models.reminder_model import Reminder
from src.pdf_templates.reminder_summary_pdf import \
    generate_reminder_summary_pdf
from infrastructure.database.database_config import get_database_config, get_environment
from src.utils.datetime_standarization_helpers import get_this_moment


base_url = os.getenv("BASE_URL")

logger = logging.getLogger("reminder_summary_service")


class ReminderSummaryService:
    def __init__(self):
        # Remove database_url and database_name since we'll use centralized connection
        self.db = None
        self.grid_fs = None

    async def initialize_db(self):
        """Initialize database connection using centralized connection system"""
        try:
            # Force a fresh connection to ensure we're in the right event loop
            from beanie import init_beanie
            from motor.motor_asyncio import (AsyncIOMotorClient,
                                             AsyncIOMotorGridFSBucket)

            # Get database config
            mongodb_url, database_name = get_database_config()

            # Create fresh client and connection for this event loop
            client = AsyncIOMotorClient(mongodb_url)
            database = client[database_name]

            # Initialize beanie with fresh connection
            await init_beanie(database=database, document_models=[Project, Reminder])

            # Create fresh GridFS instance for this event loop
            self.db = database
            self.grid_fs = AsyncIOMotorGridFSBucket(database)

            # Log which environment and database we're connecting to
            env = get_environment()
            logger.info(
                f"ReminderSummaryService initialized for {env} environment using database: {database_name}"
            )

        except Exception as e:
            logger.error(
                f"Failed to initialize database connection in ReminderSummaryService: {str(e)}"
            )
            raise

    async def get_project_info(self, project_code: str) -> Optional[Dict[str, Any]]:
        """Get project information"""
        await self.initialize_db()  # Ensure database is initialized

        project = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )
        if not project:
            return None

        return {
            "project_code": project.project_code,
            "project_location": project.project_location,
            "reminder_summary_id": project.reminder_summary_id,
        }

    async def get_project_reminders(self, project_code: str) -> List[Dict[str, Any]]:
        """Get all reminders for a project"""
        await self.initialize_db()  # Ensure database is initialized

        return await Reminder.get_project_reminders(project_code)

    async def generate_reminder_summary_pdf(
        self, project_code: str, force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """Generate reminder summary PDF for a project"""
        try:
            await self.initialize_db()  # Ensure database is initialized

            env = get_environment()
            logger.info(
                f"Generating reminder summary PDF for project {project_code} in {env} environment (force_regenerate={force_regenerate})"
            )

            # Get project information
            project_info = await self.get_project_info(project_code)
            if not project_info:
                logger.error(f"Project {project_code} not found in database")
                return {
                    "status": "error",
                    "message": f"Project {project_code} not found",
                }

            # Get reminders for the project
            reminders = await self.get_project_reminders(project_code)
            if not reminders:
                logger.warning(f"No reminders found for project {project_code}")
                return {
                    "status": "warning",
                    "message": f"No reminders found for project {project_code}",
                }

            logger.info(f"Found {len(reminders)} reminders for project {project_code}")

            # Check if PDF already exists and regeneration is not forced
            existing_pdf_id = project_info.get("reminder_summary_id")
            if existing_pdf_id and not force_regenerate:
                try:
                    # Check if the file exists in GridFS
                    from bson import ObjectId

                    if isinstance(existing_pdf_id, str):
                        existing_pdf_id = ObjectId(existing_pdf_id)
                    if await self.grid_fs.find({"_id": existing_pdf_id}).to_list(
                        length=1
                    ):
                        logger.info(
                            f"Existing PDF found for project {project_code}, returning existing PDF"
                        )
                        return {
                            "status": "exists",
                            "message": f"Reminder summary PDF already exists for project {project_code}",
                            "pdf_id": str(existing_pdf_id),
                            "download_url": f"{base_url}/reminder-summary/{existing_pdf_id}.pdf",
                        }
                except Exception as e:
                    logger.warning(
                        f"Error checking existing PDF for project {project_code}: {str(e)}, will regenerate"
                    )

            # Generate PDF content
            logger.info(f"Generating PDF content for project {project_code}...")
            pdf_content = await generate_reminder_summary_pdf(project_info, reminders)

            # Store PDF in GridFS
            filename = f"reminder_summary_{project_code}_{get_this_moment().strftime('%Y%m%d_%H%M%S')}.pdf"
            logger.info(f"Uploading PDF to GridFS with filename: {filename}")
            pdf_id = await self.grid_fs.upload_from_stream(
                filename,
                pdf_content,
                metadata={
                    "content_type": "application/pdf",
                    "project_code": project_code,
                    "generated_at": get_this_moment(),
                    "environment": env,
                    "reminder_count": len(reminders),
                },
            )

            logger.info(f"PDF uploaded to GridFS with ID: {pdf_id}")

            # Update project with reminder summary ID - with better error handling
            try:
                project = await Project.find_one(
                    Project.project_code == project_code, Project.deleted_at == None
                )
                if project:
                    old_pdf_id = project.reminder_summary_id
                    project.reminder_summary_id = str(pdf_id)
                    await project.save()
                    logger.info(
                        f"Updated project {project_code} reminder_summary_id from '{old_pdf_id}' to '{pdf_id}'"
                    )
                else:
                    logger.error(
                        f"Could not find project {project_code} to update reminder_summary_id"
                    )
                    return {
                        "status": "error",
                        "message": f"Could not find project {project_code} to update",
                    }
            except Exception as update_error:
                logger.error(
                    f"Failed to update project {project_code} with reminder_summary_id {pdf_id}: {str(update_error)}"
                )
                # Don't fail the whole operation, just log the error

            logger.info(
                f"Successfully generated reminder summary PDF for project {project_code}, PDF ID: {pdf_id}"
            )

            return {
                "status": "success",
                "message": f"Reminder summary PDF generated successfully for project {project_code}",
                "pdf_id": str(pdf_id),
                "download_url": f"{base_url}/reminder-summary/{pdf_id}.pdf",
                "reminder_count": len(reminders),
                "environment": env,
            }

        except Exception as e:
            logger.error(
                f"Error generating reminder summary PDF for project {project_code}: {str(e)}"
            )
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"Error generating reminder summary PDF: {str(e)}",
            }

    async def generate_all_project_reminder_summaries(
        self, force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """Generate reminder summary PDFs for all projects that have reminders"""
        try:
            await self.initialize_db()

            # Get all projects that have reminders
            pipeline = [
                {"$match": {"deleted_at": None}},
                {
                    "$lookup": {
                        "from": "reminder_collection",
                        "localField": "project_code",
                        "foreignField": "project_code",
                        "as": "reminders",
                    }
                },
                {"$match": {"reminders": {"$ne": []}}},
                {
                    "$project": {
                        "project_code": 1,
                        "reminder_count": {"$size": "$reminders"},
                    }
                },
            ]

            projects_with_reminders = await Project.aggregate(pipeline).to_list()

            if not projects_with_reminders:
                return {
                    "status": "warning",
                    "message": "No projects with reminders found",
                }

            results = []
            success_count = 0
            error_count = 0

            for project_data in projects_with_reminders:
                project_code = project_data["project_code"]
                try:
                    result = await self.generate_reminder_summary_pdf(
                        project_code, force_regenerate
                    )
                    results.append(
                        {
                            "project_code": project_code,
                            "status": result["status"],
                            "message": result["message"],
                            "pdf_id": result.get("pdf_id"),
                            "reminder_count": project_data["reminder_count"],
                        }
                    )

                    if result["status"] == "success":
                        success_count += 1
                    else:
                        error_count += 1

                except Exception as e:
                    logger.error(
                        f"Error generating PDF for project {project_code}: {str(e)}"
                    )
                    results.append(
                        {
                            "project_code": project_code,
                            "status": "error",
                            "message": str(e),
                            "reminder_count": project_data["reminder_count"],
                        }
                    )
                    error_count += 1

            return {
                "status": "completed",
                "message": f"Processed {len(projects_with_reminders)} projects: {success_count} successful, {error_count} errors",
                "total_projects": len(projects_with_reminders),
                "success_count": success_count,
                "error_count": error_count,
                "results": results,
            }

        except Exception as e:
            logger.error(f"Error generating all reminder summary PDFs: {str(e)}")
            return {
                "status": "error",
                "message": f"Error generating all reminder summary PDFs: {str(e)}",
            }

    async def get_reminder_summary_info(self, project_code: str) -> Dict[str, Any]:
        """Get information about reminder summary PDF for a project"""
        try:
            await self.initialize_db()

            project_info = await self.get_project_info(project_code)
            if not project_info:
                return {
                    "status": "error",
                    "message": f"Project {project_code} not found",
                }

            reminders = await self.get_project_reminders(project_code)

            return {
                "status": "success",
                "project_code": project_code,
                "project_title": project_info.get("project_title"),
                "project_location": project_info.get("project_location"),
                "reminder_count": len(reminders),
                "pdf_exists": bool(project_info.get("reminder_summary_id")),
                "pdf_id": project_info.get("reminder_summary_id"),
                "download_url": (
                    f"{base_url}/reminder-summary/{project_info.get('reminder_summary_id')}.pdf"
                    if project_info.get("reminder_summary_id")
                    else None
                ),
                "reminders": reminders,
            }

        except Exception as e:
            logger.error(
                f"Error getting reminder summary info for project {project_code}: {str(e)}"
            )
            return {
                "status": "error",
                "message": f"Error getting reminder summary info: {str(e)}",
            }


# Global service instance
reminder_summary_service = ReminderSummaryService()


# CLI functions for manual operations
async def generate_single_project_summary(
    project_code: str, force_regenerate: bool = False
):
    """Generate reminder summary for a single project"""
    result = await reminder_summary_service.generate_reminder_summary_pdf(
        project_code, force_regenerate
    )
    print(f"\nProject {project_code} - {result['status'].upper()}")
    print(f"Message: {result['message']}")
    if result.get("download_url"):
        print(f"Download URL: {result['download_url']}")
    return result
