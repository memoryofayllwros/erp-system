import logging
import urllib.parse
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.models.project_model import Project
from src.routes.user_routes import get_current_user
from infrastructure.database.database_connection import get_grid_fs

router = APIRouter()


class ProjectLocation(BaseModel):
    region: Optional[str] = None
    district: Optional[str] = None
    street: Optional[str] = None
    building: Optional[str] = None


class CompanyLocation(BaseModel):
    district: str
    street: str
    building: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class PostProject(BaseModel):
    project_title: str
    region: Optional[str] = None
    district: Optional[str] = None
    street: Optional[str] = None
    building: Optional[str] = None
    client_name: Optional[str] = None

@router.post("/add-project/", response_model=dict)
async def create_project(request: PostProject, current_user=Depends(get_current_user)):
    try:
        existing_project = await Project.find_one(
            Project.project_title == request.project_title, Project.deleted_at == None
        )
        if existing_project:
            raise HTTPException(status_code=400, detail="Project already exists")

        result = await Project.add_project_function(
            project_title=request.project_title,
            region=request.region if request.region else None,
            district=request.district if request.district else None,
            street=request.street if request.street else None,
            building=request.building if request.building else None,
            company_user_id=str(current_user.id) if (current_user.id) else None,
            client_name=request.client_name if (request.client_name) else None,
        )

        return {"message": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/read-all-projects/")
async def list_all_projects():
    try:
        projects = await Project.read_all_projects_function_by_endpoint()
        return {"status": "success", "count": len(projects), "projects": projects}
    except Exception as e:
        logging.error(f"Error in list_all_projects endpoint: {str(e)}")
        return {"status": "error", "message": str(e)}


class UpdateProject(BaseModel):
    region: Optional[str] = None
    district: Optional[str] = None
    street: Optional[str] = None
    building: Optional[str] = None


@router.put("/update-project/{project_code}/")
async def update_project(project_code: str, request: UpdateProject):

    try:
        if not project_code or not project_code.strip():
            raise HTTPException(
                status_code=400, detail="Project number cannot be empty"
            )

        # Create project_location dict, filtering out None values
        project_location = {
            k: v
            for k, v in {
                "region": request.region,
                "district": request.district,
                "street": request.street,
                "building": request.building,
            }.items()
            if v is not None
        }

        # Check if there's actually something to update
        if not project_location:
            raise HTTPException(
                status_code=400, detail="At least one location field must be provided"
            )

        result = await Project.update_project_function(
            project_code=project_code.strip(), project_location=project_location
        )

        # Handle the result based on its structure
        if isinstance(result, dict):
            if result.get("status") == "error":
                error_type = result.get("error_type", "unknown")
                status_code = 400 if error_type == "validation" else 500
                raise HTTPException(
                    status_code=status_code, detail=result.get("message")
                )
            return result
        else:
            # If result is just a message string
            return {"status": "success", "message": str(result), "project_info": None}

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class AddProjectGPS(BaseModel):
    lat: str
    lon: str
    location_name: str


@router.put("/add-project-gps-location/{project_code}/")
async def add_project_gps_location(project_code: str, request: AddProjectGPS):
    try:
        if not project_code or not project_code.strip():
            raise HTTPException(
                status_code=400, detail="Project number cannot be empty"
            )

        project_info = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )
        if not project_info:
            raise HTTPException(status_code=404, detail="Project not found")

        project_id = str(project_info.id)
        result = await Project.add_project_location_gps(
            project_id=project_id,
            latitude=request.lat,
            longitude=request.lon,
            location_name=request.location_name,
        )

        # Handle the result based on its structure
        if isinstance(result, dict):
            if result.get("status") == "error":
                error_type = result.get("error_type", "unknown")
                status_code = 400 if error_type == "validation" else 500
                raise HTTPException(
                    status_code=status_code, detail=result.get("message")
                )
            return result
        else:
            # If result is just a message string
            return {"status": "success", "message": str(result), "project_info": None}

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/delete-project-gps-location/")
async def delete_project_gps_location_by_endpoint(
    project_code: str, location_name: str, current_user=Depends(get_current_user)
):
    try:
        message = await Project.delete_project_gps_location(project_code, location_name)
        return {"status": "success", "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/delete-project-only/{project_code}/")
async def delete_project_only(
    project_code: str, current_user=Depends(get_current_user)
):
    try:
        message = await Project.delete_project_function(project_code)
        return {"status": "success", "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/delete-project-with-all-related/{project_code}/")
async def delete_project(project_code: str, current_user=Depends(get_current_user)):
    try:
        message = await Project.delete_project_with_all_related(project_code)
        return {"status": "success", "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/{project_code}/payslip/{year}/{month}/download-xlsx/")
async def read_project_payslip_xlsx(project_code: str, year: int, month: int):
    """Download the payslip XLSX for a project by year and month, using GridFS ID saved in Project.monthly_attendance_ids."""
    try:
        # Accept two-digit year like 25 -> 2025
        normalized_year = year + 2000 if year < 100 else year

        project_info = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )
        if not project_info:
            raise HTTPException(status_code=404, detail="Project not found")

        file_id_str = None
        try:
            entries = list(getattr(project_info, "monthly_attendance_ids", []) or [])
            # Prefer the most recent matching entry by scanning in reverse
            for entry in reversed(entries):
                try:
                    entry_month = int(getattr(entry, "month", None))
                    entry_year = int(getattr(entry, "year", None))
                except Exception:
                    continue
                if entry_month == int(month) and entry_year == int(normalized_year):
                    file_id_str = getattr(entry, "monthly_attendance_id", None)
                    if file_id_str:
                        break
        except Exception:
            file_id_str = None

        try:
            object_id = ObjectId(file_id_str)
        except Exception:
            raise HTTPException(
                status_code=400, detail="Invalid stored ObjectId format"
            )

        try:
            grid_fs = await get_grid_fs()
            grid_out = await grid_fs.open_download_stream(object_id)
            content = await grid_out.read()
            if not content:
                raise HTTPException(
                    status_code=404, detail="Payslip file not found in GridFS"
                )

            filename = (
                grid_out.filename
                if hasattr(grid_out, "filename")
                else f"payslip_{project_code}_{normalized_year}{str(month).zfill(2)}.xlsx"
            )

            # Properly encode filename for Content-Disposition header to handle Unicode characters
            try:
                encoded_filename = urllib.parse.quote(filename, safe="")
                content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}; filename=\"{filename}\""
            except Exception as encoding_error:
                logging.warning(
                    f"Filename encoding failed, using fallback: {str(encoding_error)}"
                )
                content_disposition = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename, safe='')}"

            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": content_disposition},
            )
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error downloading payslip XLSX: {str(e)}")
            raise HTTPException(status_code=404, detail="File not found in GridFS")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"Error in read_project_payslip_xlsx: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/project/attendance-record/{attendance_record_id}/preview/")
async def read_attendance_record_by_id(
    attendance_record_id: str, download: bool = False
):
    """Serve a attendance record PDF directly by its GridFS ID. Set download=True to force download."""
    try:
        try:
            object_id = ObjectId(attendance_record_id)
        except Exception as e:
            logging.error(f"ObjectId conversion error: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid ObjectId format")

        try:
            # Use asynchronous GridFS operations with await
            grid_fs = await get_grid_fs()
            grid_out = await grid_fs.open_download_stream(object_id)
            content = await grid_out.read()

            if not content:
                raise HTTPException(
                    status_code=404, detail="Attendance record not found"
                )

            # Get filename from GridFS if available, otherwise create one
            file_name = (
                grid_out.filename
                if hasattr(grid_out, "filename")
                else f"attendance-record-{attendance_record_id}.pdf"
            )

            # Set Content-Disposition header based on download parameter
            if download:
                # Force download mode
                try:
                    # Sanitize filename to ASCII-safe characters for the fallback filename
                    ascii_filename = "".join(
                        c if c.isascii() and c.isalnum() or c in ".-_" else "_"
                        for c in file_name
                    )
                    if not ascii_filename.endswith(".pdf"):
                        ascii_filename = f"attendance-record-{attendance_record_id}.pdf"

                    # URL encode the original filename for UTF-8 support
                    encoded_filename = urllib.parse.quote(
                        file_name.encode("utf-8"), safe=""
                    )

                    # Use RFC 5987 format for proper Unicode filename handling
                    content_disposition = f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"

                except Exception as encoding_error:
                    logging.warning(
                        f"Filename encoding failed, using fallback: {str(encoding_error)}"
                    )
                    # Fallback: use a simple ASCII filename
                    fallback_filename = f"attendance-record-{attendance_record_id}.pdf"
                    content_disposition = f'attachment; filename="{fallback_filename}"'
            else:
                # Preview mode - inline display
                content_disposition = "inline"

            return Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": content_disposition},
            )

        except Exception as e:
            logging.error(f"Error downloading attendance record file: {str(e)}")
            raise HTTPException(status_code=404, detail="File not found in GridFS")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"Error in read_attendance_record_by_id: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


from infrastructure.database.database_connection import get_file_from_gridfs


@router.get("/project/worker-info/{worker_info_id}/preview/")
async def read_worker_info_by_id(
    worker_info_id: str, current_user=Depends(get_current_user)
):
    try:
        filename, content = await get_file_from_gridfs(worker_info_id)
        try:
            encoded_filename = urllib.parse.quote(filename, safe="")
            content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}; filename=\"{filename}\""
        except Exception as encoding_error:
            logging.warning(
                f"Filename encoding failed, using fallback: {str(encoding_error)}"
            )
            content_disposition = (
                f"attachment; filename*=UTF-8''{urllib.parse.quote(filename, safe='')}"
            )

        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": content_disposition},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Unexpected error in read_worker_info_by_id: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
