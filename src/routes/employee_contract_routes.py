# check_in_routes.py
import logging
import os
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.models.user_model import User

base_url = os.getenv("BASE_URL")

logger = logging.getLogger(__name__)

router = APIRouter()


# create employee contract # daily or monthly contract
class SalaryInfo(BaseModel):
    is_daily_contract: bool  # True for daily, False for monthly
    salary_amount: str


class EmployeeInfo(BaseModel):
    chinese_name: str
    national_id_no: str
    gender: str
    mobile: List[str]
    banking_card_no: str


class CreateEmployeeContract(BaseModel):
    is_daily_contract: bool  # True for daily, False for monthly
    contract_no: str
    position: str
    worker_id: str
    probation_period: int
    bonus: str

    contract_issue_date: date
    contract_start_date: date
    salary_amount: str
    project_id: str


@router.get("/generate-default-contract-no/")
async def generate_default_contract_no(is_daily_contract: bool, project_id: str):
    """
    Generate a default contract number for the given contract type and project.
    This allows the frontend to display the default contract number to the user
    before they create the contract, giving them the option to modify it.
    """
    try:
        # Generate the default contract number
        default_contract_no = await User.create_default_contract_no(
            is_daily_contract, project_id
        )

        return JSONResponse(
            content={
                "status": "success",
                "default_contract_no": default_contract_no,
                "message": f"Default contract number generated: {default_contract_no}",
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"Project ID: {project_id}, Error generating default contract number: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/create-employee-contract/")
async def create_employee_contract(contract_data: CreateEmployeeContract):
    try:
        """
        Create an employee contract
        """
        # contract_type is now a boolean, no validation needed

        # Validate salary amount
        try:
            salary_amount_float = float(contract_data.salary_amount)
            if salary_amount_float <= 0:
                raise HTTPException(
                    status_code=400, detail="Salary amount must be greater than 0"
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid salary amount format")

        # Validate dates
        if contract_data.contract_start_date < contract_data.contract_issue_date:
            raise HTTPException(
                status_code=400,
                detail="Contract start date cannot be before issue date",
            )

        # Validate contract number uniqueness
        if await User.check_contract_no_exists(contract_data.contract_no):
            raise HTTPException(
                status_code=400,
                detail=f"Contract number {contract_data.contract_no} already exists. Please use a different contract number.",
            )

        # Store the contract in GridFS and update user record (generate contract internally)
        result = await User.create_employee_contract_function(
            worker_id=contract_data.worker_id,
            position=contract_data.position,
            is_daily_contract=contract_data.is_daily_contract,
            contract_no=contract_data.contract_no,
            project_id=contract_data.project_id,
            probation_period=contract_data.probation_period,
            contract_issue_date=contract_data.contract_issue_date,
            contract_start_date=contract_data.contract_start_date,
            bonus=contract_data.bonus,
            salary_amount=contract_data.salary_amount,
        )  # Let the function generate the contract internally

        # Check if the result indicates success or error
        if result.startswith("⚠️"):
            raise HTTPException(status_code=400, detail=result)

        return JSONResponse(content={"status": "success", "message": result})
    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_employee_contract: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{contract_id}/download")
async def download_contract_document(contract_id: str):
    """
    Download a contract document from GridFS by its ID
    """
    try:
        contract_data, error = await User.get_contract_document(contract_id)

        if error:
            raise HTTPException(status_code=400, detail=error)

        if not contract_data:
            raise HTTPException(status_code=404, detail="Contract document not found")

        # Return the document as a file download
        from fastapi.responses import Response

        return Response(
            content=contract_data["content"],
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=\"{contract_data['filename']}\""
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in download_contract_document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{contract_id}/")
async def delete_contract_document_by_endpoint(contract_id: str):
    """
    Delete a contract document from GridFS by its ID
    """
    try:
        result = await User.delete_contract_document(contract_id)

        if result.startswith("⚠️"):
            raise HTTPException(status_code=400, detail=result)

        return JSONResponse(content={"status": "success", "message": result})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in delete_contract_document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
