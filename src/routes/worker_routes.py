import base64
import logging
import os
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, field_validator

from src.models.user_model import User

router = APIRouter()


@router.get("/worker-registration-card/{worker_id}")
async def get_worker_card_pdf(worker_id: str):
    try:
        object_id = ObjectId(worker_id)
    except Exception as e:
        logging.error(f"ObjectId conversion error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    try:
        # Fetch worker directly from database
        worker = await User.find_one(User.id == object_id, User.deleted_at == None)

        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")

        if not worker.construction_worker_card or not worker.construction_worker_card:
            raise HTTPException(
                status_code=404, detail="Registration card not found for this worker"
            )

        # Get the image bytes from the base64-encoded string
        try:
            content = base64.b64decode(worker.construction_worker_card.card_image_front)
        except Exception as e:
            logging.error(f"Error decoding base64 image: {str(e)}")
            raise HTTPException(status_code=500, detail="Error decoding image data")

        if not content:
            raise HTTPException(status_code=404, detail="Card image not found")

        # Determine the content type based on the image data
        content_type = "image/jpeg"  # Default to JPEG
        if content.startswith(b"\x89PNG"):
            content_type = "image/png"
        elif content.startswith(b"%PDF"):
            content_type = "application/pdf"

        # Return the image with appropriate content type
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=worker-card-{worker_id}.jpg"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error retrieving worker card: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/worker-training-certificate/{worker_id}")
async def get_worker_training_certificate_pdf(worker_id: str):
    try:
        object_id = ObjectId(worker_id)
    except Exception as e:
        logging.error(f"ObjectId conversion error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    try:
        # Fetch worker directly from database
        worker = await User.get(object_id)

        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")

        if not worker.certified_worker_card or not worker.certified_worker_card:
            raise HTTPException(
                status_code=404, detail="Training certificate not found for this worker"
            )

        # Get the image bytes from the base64-encoded string
        try:
            content = base64.b64decode(worker.certified_worker_card.card_image_front)
        except Exception as e:
            logging.error(f"Error decoding base64 image: {str(e)}")
            raise HTTPException(status_code=500, detail="Error decoding image data")

        if not content:
            raise HTTPException(status_code=404, detail="Certificate image not found")

        # Determine the content type based on the image data
        content_type = "image/jpeg"  # Default to JPEG
        if content.startswith(b"\x89PNG"):
            content_type = "image/png"
        elif content.startswith(b"%PDF"):
            content_type = "application/pdf"

        # Return the image with appropriate content type
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=training-certificate-{worker_id}.jpg"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error retrieving training certificate: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all-workers-info-xlsx/{worker_list_id}")
async def export_worker_list_excel(worker_list_id: str):
    try:
        from infrastructure.database.database_connection import get_grid_fs
        grid_fs = await get_grid_fs()
        
        try:
            object_id = ObjectId(worker_list_id)
        except Exception as e:
            logging.error(f"ObjectId conversion error: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid ObjectId format")
        
        # Open the download stream
        grid_out = await grid_fs.open_download_stream(object_id)
        file_content = await grid_out.read()
        
        if not file_content:
            raise HTTPException(status_code=404, detail="Worker list not found or is empty")
        
        # Get the original filename from metadata if available
        filename = grid_out.filename if hasattr(grid_out, "filename") else f"worker_list.xlsx"
        
        return Response(
            content=file_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error exporting worker list: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
