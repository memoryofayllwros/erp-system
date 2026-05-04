import logging
import os

from beanie import init_beanie
from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from src.utils.datetime_standarization_helpers import get_this_moment
from src.models.attendance_record_model import AttendanceRecord
from src.models.attendance_via_image_model import AttendanceViaImageModel
from src.models.end_client_model import EndClient
from src.models.shift_rule_model import ShiftConfiguration
from src.models.attendance_via_gps_model import AttendanceViaGpsModel
from src.models.client_company_model import ClientCompany
from src.models.conversation_model import Conversation
from src.models.project_count_model import ProjectCounter
from src.models.project_model import Project
from src.models.reminder_model import Reminder
from src.models.user_model import User
from src.models.application_and_approval_model import ApplicationAndApproval
from src.models.worker_project_model import WorkerProjectContractInfo
from infrastructure.database.database_config import get_database_config, get_environment

APP_ENV = os.getenv("APP_ENV", "development")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

# Global variables to hold the client and database
client = None
db = None
grid_fs = None


async def get_grid_fs():

    global client, db, grid_fs

    if grid_fs is None:
        logger.info("GridFS not initialized, creating new connection...")
        await init()

    if grid_fs is None:
        raise Exception("Failed to initialize GridFS connection")

    return grid_fs


async def get_database():
    """
    Get database instance, creating connection if needed.
    """
    global client, db, grid_fs

    if db is None:
        logger.info("Database not initialized, creating new connection...")
        await init()

    if db is None:
        raise Exception("Failed to initialize database connection")

    return db


async def init():
    global client, db, grid_fs

    try:
        # Use centralized database configuration
        env = get_environment()
        database_url, database_name = get_database_config()

        # Create the MongoDB client inside the async context
        client = AsyncIOMotorClient(database_url)
        db = client[database_name]
        grid_fs = AsyncIOMotorGridFSBucket(db)

        logger.info(
            f"Connecting to MongoDB in {env} environment using database: {database_name}"
        )

        await init_beanie(
            db,
            document_models=[
                Conversation,
                Project,
                User,
                ProjectCounter,
                ClientCompany,
                Reminder,
                AttendanceRecord,
                AttendanceViaImageModel,
                AttendanceViaGpsModel,
                EndClient,
                ShiftConfiguration,
                ApplicationAndApproval,
                WorkerProjectContractInfo,
            ],
        )

        logger.info("MongoDB connection and Beanie initialization successful")

    except Exception as e:
        logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
        raise


async def save_image_bytes_to_gridfs(
    image_bytes: bytes, filename: str, metadata: dict = None
) -> str:
    """
    Save image bytes to GridFS and return the file ID.

    Args:
        image_bytes: The image data as bytes
        filename: The filename for the image
        metadata: Optional metadata dictionary

    Returns:
        str: GridFS file ID
    """
    try:
        from io import BytesIO

        grid_fs = await get_grid_fs()

        # Create metadata if not provided
        if metadata is None:
            metadata = {}

        # Add upload timestamp to metadata
        metadata["upload_date"] = get_this_moment().isoformat()

        # Upload to GridFS
        file_id = await grid_fs.upload_from_stream(
            filename=filename, source=BytesIO(image_bytes), metadata=metadata
        )

        logging.info(f"Image uploaded to GridFS: {filename} with ID: {file_id}")
        return str(file_id)

    except Exception as e:
        logging.error(f"GridFS upload error: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to save image to GridFS: {str(e)}"
        )


async def get_file_from_gridfs(file_id: str):
    try:
        object_id = ObjectId(file_id)
    except Exception as e:
        logging.error(f"ObjectId conversion error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    try:
        grid_fs = await get_grid_fs()
        grid_out = await grid_fs.open_download_stream(object_id)
        content = await grid_out.read()

        if not content:
            raise HTTPException(status_code=404, detail="File not found")

        filename = (
            grid_out.filename if hasattr(grid_out, "filename") else f"file-{file_id}"
        )
        return filename, content

    except Exception as e:
        logging.error(f"GridFS read error: {str(e)}")
        raise HTTPException(status_code=404, detail="File not found in GridFS")
