import os
from typing import Tuple

database_url = os.getenv("DATABASE_URL")


def get_environment() -> str:
    """Get the current environment."""
    return os.getenv("APP_ENV", "development")


def get_database_config():

    env = get_environment()

    if env == "production":
        database_name = "production_database"
    else:
        database_name = "development_database"

    return database_url, database_name
