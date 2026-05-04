from datetime import datetime
from typing import Optional, Dict, Any

from beanie import Document
from pydantic import BaseModel, Field, model_validator, computed_field

from src.utils.datetime_standarization_helpers import get_this_moment
class EndClientLocation(BaseModel):
    district: str
    street: str
    building: Optional[str] = None


class Logo(BaseModel):
    logo_data: str
    logo_name: str
    logo_type: str


class EndClient(Document):
    """company_chinese_name and company_english_name are optional, but at least one of them must be provided"""
    end_client_chinese_name: Optional[str] = None
    end_client_english_name: Optional[str] = None
    fax: Optional[str] = None
    website: Optional[str] = None
    logo_document: Optional[Logo] = None
    location: Optional[EndClientLocation] = None
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    class Settings:
        name = "end_client_collection"
        
    @model_validator(mode='before')
    @classmethod
    def check_end_client_name_exists(cls, values: Any) -> Any:
        """Validate that at least one of end_client_chinese_name or end_client_english_name is provided"""
        if isinstance(values, dict):
            chinese_name = values.get('end_client_chinese_name')
            english_name = values.get('end_client_english_name')
            
            if chinese_name is None and english_name is None:
                raise ValueError("At least one of end_client_chinese_name or end_client_english_name must be provided")
                
        return values

    @computed_field
    @property
    def company_name(self) -> str:
        return self.end_client_chinese_name or self.end_client_english_name


    @classmethod
    async def add_end_client_function(
        cls,
        end_client_chinese_name: Optional[str] = None,
        end_client_english_name: Optional[str] = None,
        fax: Optional[str] = None,
        website: Optional[str] = None,
        end_client_logo: Optional[Logo] = None,
        location: Optional[EndClientLocation] = None,
    ): 
        try:
            # Check if at least one name is provided
            if end_client_chinese_name is None and end_client_english_name is None:
                return {
                    "status": "error",
                    "message": "At least one of end_client_chinese_name or end_client_english_name must be provided",
                }
            
            # Check if end client with same name already exists
            existing_client = None
            query_conditions = []
            
            if end_client_chinese_name:
                query_conditions.append(cls.end_client_chinese_name == end_client_chinese_name)
            if end_client_english_name:
                query_conditions.append(cls.end_client_english_name == end_client_english_name)
                
            if query_conditions:
                existing_client = await cls.find_one(
                    {"$or": query_conditions, "deleted_at": None}
                )
            
            if existing_client:
                return {
                    "status": "error",
                    "message": f"End Client {end_client_chinese_name or ''} or {end_client_english_name or ''} already exists",
                }

            new_client = cls(
                end_client_chinese_name=end_client_chinese_name,
                end_client_english_name=end_client_english_name,
                fax=fax if fax is not None else None,
                website=website if website is not None else None,
                location=location if location is not None else None,
                logo_document=end_client_logo if end_client_logo is not None else None,
                created_at=get_this_moment(),
            )
            await new_client.insert()

            return {"status": "success", "message": f"成功新增End Client: {end_client_chinese_name} 或 {end_client_english_name}"}
        except Exception as e:
            return {"status": "error", "message": f"新增End Client時發生錯誤: {str(e)}"}
