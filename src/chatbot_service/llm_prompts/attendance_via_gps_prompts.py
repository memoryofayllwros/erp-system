import logging
from datetime import datetime, timedelta
from math import cos, radians
from typing import List, Tuple

from dotenv import load_dotenv
from scipy.spatial import KDTree

from src.utils.standardization_helpers import standardize_timestamp
from src.utils.datetime_standarization_helpers import get_this_moment

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

load_dotenv()

EARTH_RADIUS_M = 6371000
DEFAULT_RADII_METERS = [
    50,
    100,
    150,
    200,
    250,
    300,
    350,
    400,
    450,
    500,
    550,
    600,
    650,
    700,
]


def latlon_to_xy(lat: float, lon: float) -> Tuple[float, float]:
    x = EARTH_RADIUS_M * radians(lon) * cos(radians(lat))
    y = EARTH_RADIUS_M * radians(lat)
    return (x, y)


def build_project_kdtree(
    project_locations: List[dict],
) -> Tuple[KDTree, List[Tuple[float, float]]]:
    xy_coords = [
        latlon_to_xy(loc["lat"], loc["long"])
        for loc in project_locations
        if "lat" in loc and "long" in loc
    ]
    tree = KDTree(xy_coords)
    return tree, xy_coords


async def progressive_location_gps_match(lat: str, lon: str):
    try:
        try:
            lat = float(lat)
            lon = float(lon)

        except ValueError:
            logger.error(f"Invalid GPS format: '{lat}, {lon}'")
            return_documents = {
                "project_id": None,
                "project_code": None,
                "message": f"Invalid GPS format: '{lat}, {lon}'",
            }
            return return_documents

        from src.models.project_model import Project
        from infrastructure.database.database_connection import get_database

        await get_database()

        project_locations = await Project.get_all_project_locations_gps()
        logging.info(
            f"project_locations in progressive_location_gps_match: {len(project_locations)} locations found"
        )

        if project_locations == []:
            logger.info("No projects found in database")
            return_documents = {
                "project_id": None,
                "project_code": None,
                "message": "No projects found in database",
            }
            return return_documents

        search_ranges = DEFAULT_RADII_METERS
        tree, _ = build_project_kdtree(project_locations)
        user_xy = latlon_to_xy(lat, lon)

        for radius in search_ranges:
            indices = tree.query_ball_point(user_xy, r=radius)
            if indices:
                project_id = str(project_locations[indices[0]]["project_id"])
                project_code = str(project_locations[indices[0]]["project_code"])
                logger.info(
                    f"GPS match found within {radius} meters for location: {lat}, {lon}, \
                            project_id: {project_id}, project_code: {project_code}"
                )

                return_documents = {
                    "project_id": project_id,
                    "project_code": project_code,
                    "message": f"GPS match found within {radius} meters for your location: {lat}, {lon}",
                }
                logging.info(
                    f"successful return_documents in progressive_location_gps_match: {return_documents}"
                )
                return return_documents
            else:
                logger.info(
                    f"No project location match found within {radius} meters for location: {lat}, {lon}; expanding radius..."
                )

        max_range = max(search_ranges)
        logger.info(
            f"No project location match found within {max_range} meters for location: {lat}, {lon}"
        )
        return_documents = {
            "project_id": None,
            "project_code": None,
            "message": f"喺你依家嘅位置（{lat}, {lon}）{max_range} 米內，搵唔到啱嘅工程地點喎。",  # There is no matching project location within {max_range} meters for your location: {lat}, {lon}
        }
        logging.info(
            f"unsuccessful return_documents in progressive_location_gps_match: {return_documents}"
        )
        return return_documents
    except Exception as e:
        logger.exception(f"Error in progressive location GPS match: {str(e)}")
        return_documents = {
            "project_id": None,
            "project_code": None,
            "message": f"Error in progressive location GPS match: {str(e)}",
        }
        logging.info(
            f"unsuccessful return_documents in progressive_location_gps_match: {return_documents}"
        )
        return return_documents


async def timestamp_benchmark(
    timestamp: datetime,
):  # "timestamp": "2025-07-29 10:00:00", no more than 5 minutes old, datetime object
    try:

        timestamp_hk = standardize_timestamp(timestamp)
        now_hk = get_this_moment()
        time_diff = now_hk - timestamp_hk
        return True if abs(time_diff) <= timedelta(minutes=5) else False
    except Exception as e:
        return False
