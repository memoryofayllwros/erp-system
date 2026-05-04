import logging
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.models.project_model import Project, ProjectGPSLocation
from src.routes.user_routes import get_current_user
from src.models_business_logic.nearby_project_helpers import NearbyProjectHelper, NearbyProjectsRequest
router = APIRouter()



@router.post("/api/nearby-projects")
async def get_nearby_projects_by_endpoint(request: NearbyProjectsRequest) -> List[Dict[str, Any]]:
    """Get projects near the specified location"""
    try:
        nearby_projects = await NearbyProjectHelper.get_nearby_projects_function(request)
        return nearby_projects
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting nearby projects in nearby_projects_routes: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get nearby projects: {str(e)}"

        )

@router.get("/api/projects/{project_id}/locations")
async def get_project_locations_by_endpoint(project_id: str) -> Dict[str, Any]:
    try:
        project_locations = await Project.get_project_locations_function(project_id)
        return project_locations
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting project locations in nearby_projects_routes: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get project locations: {str(e)}"
        )