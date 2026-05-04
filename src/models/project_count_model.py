from beanie import Document
from pydantic import Field
from typing import Optional


class ProjectCounter(Document):
    year: int
    project_count: int = Field(default=0)
    client_company_id: Optional[str] = None

    class Settings:
        name = "project_counter_collection"
