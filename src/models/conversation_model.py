import logging
from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")


class Conversation(Document):
    sender: str
    message: str
    response: str
    created_at: datetime = Field(default_factory=datetime.now)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "conversation_collection"

    class Config:
        arbitrary_types_allowed = True
