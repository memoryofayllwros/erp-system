from datetime import datetime


def check_location_validity(gps_location):
    if not gps_location:
        return False
    lat, lon = gps_location.split(",")
    if not lat or not lon:
        return False
    return True


def check_timestamp_validity(
    timestamp,
):  # 	Detect images with EXIF timestamps > 5 minutes old
    if not timestamp:
        return False
    try:
        datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


import os

google_maps_url = os.getenv("GOOGLE_MAPS_URL")
google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

import logging
from typing import Optional

from googlemaps import Client as GoogleMaps


def get_official_location(
    region: str,
    district: str,
    street: str,
    building: Optional[str] = None,
    google_maps_api_key: str = google_maps_api_key,
) -> Optional[dict]:
    gmaps = GoogleMaps(key=google_maps_api_key)

    try:
        # Construct a full address string
        address = f"{building or ''}, {street}, {district}, {region}"
        logging.info(f"Searching for address: {address}")

        result = gmaps.geocode(address)
        if result:
            best_match = result[0]
            logging.info(f"Matched address: {best_match['formatted_address']}")
            best_match_address = best_match["formatted_address"]
            address_components = best_match["address_components"]

            return {
                "formatted_address": best_match_address,
                "address_components": address_components,
            }
        else:
            logging.warning("No match found for the address")
            return None
    except Exception as e:
        logging.error(f"Failed to match official location: {e}")
        return None
