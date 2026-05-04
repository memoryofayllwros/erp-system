import logging
import math
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from src.models.project_model import Project


class NearbyProjectsRequest(BaseModel):
    latitude: float = Field(
            ..., ge=-90, le=90, description="Latitude between -90 and 90"
        )
    longitude: float = Field(
            ..., ge=-180, le=180, description="Longitude between -180 and 180"
        )
    radius: int = Field(
            5000, ge=100, le=50000, description="Search radius in meters (100m-50km)"
        )



class NearbyProjectHelper:

    @staticmethod
    def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS coordinates in meters using Haversine formula"""
        R = 6371000  # Earth's radius in meters
        # Convert latitude and longitude from degrees to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Haversine formula
        dlon = lon2_rad - lon1_rad
        dlat = lat2_rad - lat1_rad
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c

        return distance
        


    @classmethod
    async def get_nearby_projects_function(cls, request: NearbyProjectsRequest) -> List[Dict[str, Any]]:
        
        all_projects = await Project.find(Project.deleted_at == None).to_list()

        nearby_projects = []

        for project in all_projects:
            try:
                # Skip projects without GPS locations or required fields
                if not project.project_gps_location:
                    continue

                # Skip projects missing required fields
                if not hasattr(project, "project_title") or not project.project_title:
                    project_id_str = (
                        str(project.id) if hasattr(project, "id") else "unknown"
                    )
                    logging.warning(
                        f"Project {project_id_str} missing project_title, skipping"
                    )
                    continue

                if not hasattr(project, "project_code") or not project.project_code:
                    project_id_str = (
                        str(project.id) if hasattr(project, "id") else "unknown"
                    )
                    logging.warning(
                        f"Project {project_id_str} missing project_code, skipping"
                    )
                    continue

                # Check each GPS location of the project
                for location in project.project_gps_location:
                    try:
                        project_lat = float(location.lat)
                        project_lon = float(location.lon)

                        # Calculate distance
                        distance = NearbyProjectHelper.calculate_distance(
                            request.latitude,
                            request.longitude,
                            project_lat,
                            project_lon,
                        )

                        # If within radius, add to nearby projects
                        if distance <= request.radius:
                            project_dict = {
                                "id": str(project.id),
                                "project_code": project.project_code,
                                "project_title": project.project_title,
                                "project_gps_location": [
                                    {
                                        "lat": location.lat,
                                        "lon": location.lon,
                                        "location_name": location.location_name,
                                    }
                                ],
                            }

                            nearby_projects.append(project_dict)
                            # We found at least one location within radius, no need to check other locations
                            break
                    except (ValueError, TypeError, AttributeError) as e:
                        logging.warning(
                            f"Invalid GPS coordinates for project {getattr(project, 'project_code', project.id)}: {e}"
                        )
                        continue
            except Exception as e:
                project_id_str = (
                    str(project.id) if hasattr(project, "id") else "unknown"
                )
                logging.warning(f"Error processing project {project_id_str}: {e}")
                continue

        return nearby_projects


