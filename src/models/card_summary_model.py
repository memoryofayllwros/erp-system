import os

from beanie import Document
from dotenv import load_dotenv
from pydantic import Field

base_url = os.getenv("BASE_URL")

load_dotenv()


class CardSummary(Document):
    card_summary_id: str = Field(
        ..., min_length=1, description="Unique card summary id"
    )  # only one card summary id for all workers

    class Settings:
        name = "card_summary_collection"

    class Config:
        arbitrary_types_allowed = True
