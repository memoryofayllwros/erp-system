from datetime import datetime
from typing import Optional, Dict, Any

from beanie import Document
from pydantic import BaseModel, Field, model_validator, computed_field
from bson import ObjectId
import logging
from beanie.operators import Set

from src.utils.datetime_standarization_helpers import get_this_moment
class CompanyLocation(BaseModel):
    district: str
    street: str
    building: Optional[str] = None


class Logo(BaseModel):
    logo_data: str
    logo_name: str
    logo_type: str


class ClientCompany(Document):
    """company_chinese_name and company_english_name are optional, but at least one of them must be provided"""
    company_chinese_name: Optional[str] = None
    company_english_name: Optional[str] = None
    worker_list_id: Optional[str] = None
    fax: Optional[str] = None
    website: Optional[str] = None
    logo_document: Optional[Logo] = None
    location: Optional[CompanyLocation] = None
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    class Settings:
        name = "client_company_collection"
        
    @model_validator(mode='before')
    @classmethod
    def check_company_name_exists(cls, values: Any) -> Any:
        """Validate that at least one of company_chinese_name or company_english_name is provided"""
        if isinstance(values, dict):
            chinese_name = values.get('company_chinese_name')
            english_name = values.get('company_english_name')
            
            if chinese_name is None and english_name is None:
                raise ValueError("At least one of company_chinese_name or company_english_name must be provided")
                
        return values

    @computed_field
    @property
    def company_name(self) -> str:
        return self.company_chinese_name or self.company_english_name


    @classmethod
    async def update_worker_list_id(cls, 
                                          client_company_id: str, 
                                          worker_list_id: str
                                          ):
        try:
            client_company = await cls.find_one(
                cls.id == ObjectId(client_company_id), cls.deleted_at == None
            )
            if not client_company:
                return {
                    "status": "error",
                    "message": f"⚠️ Client company not found with id {client_company_id}",
                }
            await client_company.update(Set({cls.worker_list_id: str(worker_list_id)}))
            await client_company.save()
            return {
                "status": "success",
                "message": f"✅ Successfully updated worker_list_id for client company {client_company_id}",
                "worker_list_id": str(worker_list_id),
            }
        except Exception as e:
            logging.error(f"Error in update_worker_list_id: {str(e)}")
            return f"⚠️ {str(e)}"




    @classmethod
    async def add_client_company_function(
        cls,
        company_chinese_name: Optional[str] = None,
        company_english_name: Optional[str] = None,
        fax: Optional[str] = None,
        website: Optional[str] = None,
        company_logo: Optional[Logo] = None,
        location: Optional[CompanyLocation] = None,
    ): 
        try:
            # Check if at least one name is provided
            if company_chinese_name is None and company_english_name is None:
                return {
                    "status": "error",
                    "message": "At least one of company_chinese_name or company_english_name must be provided",
                }
            
            # Check if company with same name already exists
            existing_client = None
            query_conditions = []
            
            if company_chinese_name:
                query_conditions.append(cls.company_chinese_name == company_chinese_name)
            if company_english_name:
                query_conditions.append(cls.company_english_name == company_english_name)
                
            if query_conditions:
                existing_client = await cls.find_one(
                    {"$or": query_conditions, "deleted_at": None}
                )
            
            if existing_client:
                return {
                    "status": "error",
                    "message": f"公司 {company_chinese_name or ''} 或 {company_english_name or ''} 已經存在",
                }

            new_client = cls(
                company_chinese_name=company_chinese_name,
                company_english_name=company_english_name,
                fax=fax if fax is not None else None,
                website=website if website is not None else None,
                location=location if location is not None else None,
                logo_document=company_logo if company_logo is not None else None,
                created_at=get_this_moment(),
            )
            await new_client.insert()

            return {"status": "success", "message": f"成功新增公司: {company_chinese_name} 或 {company_english_name}"}
        except Exception as e:
            return {"status": "error", "message": f"新增公司時發生錯誤: {str(e)}"}
