"""
Client Company Routes
"""

from typing import Optional
from fastapi import (
    APIRouter, HTTPException, UploadFile, File, Form, Depends
)
from pydantic import BaseModel, Field
from src.models.client_company_model import ClientCompany, CompanyLocation, Logo

router = APIRouter(prefix="/client-company", tags=["Client Company"])


# ================================
# Request / Response Models
# ================================

class CompanyLocationRequest(BaseModel):
    district: str = Field(..., description="District where the company is located")
    street: str = Field(..., description="Street address")
    building: Optional[str] = Field(None, description="Building name (optional)")


class ClientCompanyRequest(BaseModel):
    company_chinese_name: Optional[str] = Field(None, description="Chinese company name")
    company_english_name: Optional[str] = Field(None, description="English company name")
    website: Optional[str] = Field(None, description="Company website")
    location: Optional[CompanyLocationRequest] = Field(None, description="Company location details")


class ClientCompanyResponse(BaseModel):
    status: str
    message: str
    data: Optional[dict] = None


# ================================
# Route: Add Client Company
# ================================

@router.post(
    "/add",
    response_model=ClientCompanyResponse
)
async def create_client_company(
    company_chinese_name: Optional[str] = Form(None),
    company_english_name: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    street: Optional[str] = Form(None),
    building: Optional[str] = Form(None),
    logo: UploadFile = File(...),
):
    logo_bytes = await logo.read()
    
    # Import here to avoid circular imports
    from infrastructure.database.database_connection import save_image_bytes_to_gridfs
    
    # Save logo to GridFS directly
    logo_id = await save_image_bytes_to_gridfs(
        image_bytes=logo_bytes,
        filename=logo.filename,
        metadata={"content_type": logo.content_type}
    )
    
    # Create location object if district and street are provided
    location = None
    if district and street:
        location = CompanyLocation(
            district=district,
            street=street,
            building=building
        )

    result = await ClientCompany.add_client_company_function(
        company_chinese_name=company_chinese_name,
        company_english_name=company_english_name,
        website=website,
        logo_id=logo_id,  # Use the GridFS ID directly
        location=location,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Unknown error"))

    return ClientCompanyResponse(
        status="success",
        message=result.get("message", "Client company created successfully."),
        data=result.get("data"),
    )


@router.get("/get-all", response_model=ClientCompanyResponse, summary="Get all client companies")
async def get_all_client_companies():
    """
    Retrieve a list of all active client companies.
    """
    try:
        # Find all non-deleted companies
        companies_data = await ClientCompany.get_all_client_companies_function()
        return ClientCompanyResponse(
            status="success",
            message=f"Successfully retrieved {len(companies_data)} client companies",
            data={"companies": companies_data}
        )
    except Exception as e:
        return ClientCompanyResponse(
            status="error",
            message=f"Failed to retrieve client companies: {str(e)}",
            data=None
        )


@router.get("/specific/{company_id}", response_model=ClientCompanyResponse, summary="Get client company by ID")
async def get_client_company(company_id: str):
    """
    Retrieve a specific client company by its ID.
    """
    try:
        result = await ClientCompany.get_specific_client_company_function(company_id)
        if result["status"] == "error":
            if "not found" in result["message"].lower():
                raise HTTPException(status_code=404, detail=result["message"])
            raise HTTPException(status_code=500, detail=result["message"])
        
        return ClientCompanyResponse(
            status=result["status"],
            message=result["message"],
            data=result["data"]
        )
    except HTTPException:
        raise
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Client company not found")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve client company: {str(e)}")


@router.put("/update/{company_id}", response_model=ClientCompanyResponse, summary="Update client company")
async def update_client_company(
    company_data: ClientCompanyRequest,
    company_id: str
):
    """
    Update an existing client company's information.
    """
    try:
        # Check if company exists
        company = await ClientCompany.get(company_id)
        if not company or company.deleted_at:
            raise HTTPException(status_code=404, detail="Client company not found")
        
        # Check if at least one name is provided
        if company_data.company_chinese_name is None and company_data.company_english_name is None:
            raise HTTPException(
                status_code=400, 
                detail="At least one of company_chinese_name or company_english_name must be provided"
            )
        
        # Check for name conflicts with other companies
        if company_data.company_chinese_name or company_data.company_english_name:
            query_conditions = []
            
            if company_data.company_chinese_name:
                query_conditions.append(ClientCompany.company_chinese_name == company_data.company_chinese_name)
            if company_data.company_english_name:
                query_conditions.append(ClientCompany.company_english_name == company_data.company_english_name)
                
            if query_conditions:
                existing_client = await ClientCompany.find_one(
                    {"$and": [
                        {"$or": query_conditions}, 
                        {"deleted_at": None},
                        {"_id": {"$ne": company.id}}
                    ]}
                )
                
                if existing_client:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Company with name {company_data.company_chinese_name or ''} or {company_data.company_english_name or ''} already exists"
                    )
        
        # Update company fields
        if company_data.company_chinese_name is not None:
            company.company_chinese_name = company_data.company_chinese_name
        if company_data.company_english_name is not None:
            company.company_english_name = company_data.company_english_name
        if company_data.website is not None:
            company.website = company_data.website
            
        # Update location if provided
        if company_data.location:
            company.location = CompanyLocation(
                district=company_data.location.district,
                street=company_data.location.street,
                building=company_data.location.building
            )
            
        # Update logo if provided
        if company_data.logo_document:
            company.logo_document = Logo(
                logo_data=company_data.logo_document.logo_data,
                logo_name=company_data.logo_document.logo_name,
                logo_type=company_data.logo_document.logo_type
            )
            
        await company.save()
        
        return {
            "status": "success",
            "message": f"Successfully updated client company: {company.company_name}",
            "data": None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update client company: {str(e)}")


@router.delete("/delete/{company_id}", response_model=ClientCompanyResponse, summary="Delete client company")
async def delete_client_company(company_id: str):
    """
    Soft delete a client company by setting its deleted_at timestamp.
    """
    try:
        result = await ClientCompany.delete_client_company_function(company_id)
        if result["status"] == "error":
            if "not found" in result["message"].lower():
                raise HTTPException(status_code=404, detail=result["message"])
            raise HTTPException(status_code=500, detail=result["message"])
        
        return ClientCompanyResponse(
            status=result["status"],
            message=result["message"],
            data=result["data"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete client company: {str(e)}")

