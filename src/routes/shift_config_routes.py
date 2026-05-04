import logging
from datetime import datetime, time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.models.shift_config_model import (
    Shift, 
    ShiftRule,
    TimeWindow,
    OvertimeRule
)
from src.models_business_logic.shift_config_helpers import ShiftConfigHelper
from src.routes.user_routes import get_current_user

router = APIRouter()


class TimeWindowModel(BaseModel):
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    is_overnight: bool = False
    display_name: Optional[str] = None

class ShiftConfigModel(BaseModel):
    shift_code: str
    shift_name: str
    check_in_window: TimeWindowModel
    check_out_window: TimeWindowModel
    shift_start_hour: int
    shift_start_minute: int
    shift_end_hour: int
    shift_end_minute: int
    is_overnight: bool = False
    overtime_eligible: bool = False
    min_duration_minutes: int = 0
    max_duration_minutes: Optional[int] = None
    late_grace_period_minutes: int = 1
    early_grace_period_minutes: int = 0
    display_names: Dict[str, str] = {}


class AddShiftConfigRequest(BaseModel):
    client_company_id: str
    shift_config: ShiftConfigModel


@router.post("/add-shift-config/", response_model=dict)
async def add_shift_config(request: AddShiftConfigRequest, current_user=Depends(get_current_user)):
    """Add a new shift configuration to a project"""
    try:
        
        # Get the project's shift configuration
        config = await Shift.get_shift_info_for_project(request.client_company_id)
        if not config:
            raise HTTPException(status_code=404, detail="Project shift configuration not found")
        
        # Check if configuration with same code already exists
        if request.shift_config.shift_code in config.shift_configurations:
            raise HTTPException(
                status_code=400, 
                detail=f"Shift configuration with code '{request.shift_config.shift_code}' already exists"
            )
        
        # Convert the request model to a Shift
        check_in_window = TimeWindow.create(
            start_hour=request.shift_config.check_in_window.start_hour,
            start_minute=request.shift_config.check_in_window.start_minute,
            end_hour=request.shift_config.check_in_window.end_hour,
            end_minute=request.shift_config.check_in_window.end_minute,
            is_overnight=request.shift_config.check_in_window.is_overnight,
            display_name=request.shift_config.check_in_window.display_name or ""
        )
        
        check_out_window = TimeWindow.create(
            start_hour=request.shift_config.check_out_window.start_hour,
            start_minute=request.shift_config.check_out_window.start_minute,
            end_hour=request.shift_config.check_out_window.end_hour,
            end_minute=request.shift_config.check_out_window.end_minute,
            is_overnight=request.shift_config.check_out_window.is_overnight,
            display_name=request.shift_config.check_out_window.display_name or ""
        )
        
        # Create overtime rule if eligible
        overtime_rule = None
        if request.shift_config.overtime_eligible:
            overtime_rule = OvertimeRule.create_standard()
        
        new_config = Shift(
            client_company_id=request.client_company_id,
            shift_name=request.shift_config.shift_name,
            shift_code=request.shift_config.shift_code,
            check_in_window=check_in_window,
            check_out_window=check_out_window,
            shift_start=time(request.shift_config.shift_start_hour, request.shift_config.shift_start_minute),
            shift_end=time(request.shift_config.shift_end_hour, request.shift_config.shift_end_minute),
            is_overnight=request.shift_config.is_overnight,
            overtime_eligible=request.shift_config.overtime_eligible,
            overtime_rule=overtime_rule,
            min_duration_minutes=request.shift_config.min_duration_minutes,
            max_duration_minutes=request.shift_config.max_duration_minutes,
            late_grace_period_minutes=request.shift_config.late_grace_period_minutes,
            early_grace_period_minutes=request.shift_config.early_grace_period_minutes,
            display_names=request.shift_config.display_names
        )
        
        # Add the configuration
        config.shift_configurations[request.shift_config.shift_code] = new_config
        
        # Save the updated configuration
        config.updated_at = get_this_moment()
        await config.save()
        
        # Clear the cache to ensure fresh data is loaded next time
        ShiftConfigHelper.clear_cache(request.client_company_id)
        
        return {"status": "success", "message": "Shift configuration added successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error adding shift configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class UpdateShiftConfigRequest(BaseModel):
    client_company_id: str
    shift_code: str
    shift_config: ShiftConfigModel


@router.put("/update-shift-config/", response_model=dict)
async def update_shift_config(request: UpdateShiftConfigRequest, current_user=Depends(get_current_user)):
    """Update an existing shift configuration"""
    try:
        
        # Get the project's shift configuration
        config = await Shift.get_shift_info_for_project(request.client_company_id)
        if not config:
            raise HTTPException(status_code=404, detail="Project shift configuration not found")
        
        # Check if the configuration exists
        if request.shift_code not in config.shift_configurations:
            raise HTTPException(
                status_code=404, 
                detail=f"Shift configuration with code '{request.shift_code}' not found"
            )
        
        # Convert the request model to a Shift
        check_in_window = TimeWindow.create(
            start_hour=request.shift_config.check_in_window.start_hour,
            start_minute=request.shift_config.check_in_window.start_minute,
            end_hour=request.shift_config.check_in_window.end_hour,
            end_minute=request.shift_config.check_in_window.end_minute,
            is_overnight=request.shift_config.check_in_window.is_overnight,
            display_name=request.shift_config.check_in_window.display_name or ""
        )
        
        check_out_window = TimeWindow.create(
            start_hour=request.shift_config.check_out_window.start_hour,
            start_minute=request.shift_config.check_out_window.start_minute,
            end_hour=request.shift_config.check_out_window.end_hour,
            end_minute=request.shift_config.check_out_window.end_minute,
            is_overnight=request.shift_config.check_out_window.is_overnight,
            display_name=request.shift_config.check_out_window.display_name or ""
        )
        
        # Create overtime rule if eligible
        overtime_rule = None
        if request.shift_config.overtime_eligible:
            overtime_rule = OvertimeRule.create_standard()
        
        updated_config = Shift(
            client_company_id=request.client_company_id,
            shift_name=request.shift_config.shift_name,
            shift_code=request.shift_config.shift_code,
            check_in_window=check_in_window,
            check_out_window=check_out_window,
            shift_start=time(request.shift_config.shift_start_hour, request.shift_config.shift_start_minute),
            shift_end=time(request.shift_config.shift_end_hour, request.shift_config.shift_end_minute),
            is_overnight=request.shift_config.is_overnight,
            overtime_eligible=request.shift_config.overtime_eligible,
            overtime_rule=overtime_rule,
            min_duration_minutes=request.shift_config.min_duration_minutes,
            max_duration_minutes=request.shift_config.max_duration_minutes,
            late_grace_period_minutes=request.shift_config.late_grace_period_minutes,
            early_grace_period_minutes=request.shift_config.early_grace_period_minutes,
            display_names=request.shift_config.display_names
        )
        
        # Update the configuration
        if request.shift_code != request.shift_config.shift_code:
            # If the code has changed, remove the old one and add the new one
            del config.shift_configurations[request.shift_code]
            config.shift_configurations[request.shift_config.shift_code] = updated_config
        else:
            # Otherwise just update the existing one
            config.shift_configurations[request.shift_code] = updated_config
        
        # Save the updated configuration
        config.updated_at = get_this_moment()
        await config.save()
        
        # Clear the cache to ensure fresh data is loaded next time
        ShiftConfigHelper.clear_cache(request.client_company_id)
        
        return {"status": "success", "message": "Shift configuration updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating shift configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class DeleteShiftConfigRequest(BaseModel):
    client_company_id: str
    shift_code: str


@router.delete("/delete-shift-config/", response_model=dict)
async def delete_shift_config(request: DeleteShiftConfigRequest, current_user=Depends(get_current_user)):
    """Delete a shift configuration"""
    try:
        
        # Get the project's shift configuration
        config = await Shift.get_shift_info_for_project(request.client_company_id)
        if not config:
            raise HTTPException(status_code=404, detail="Project shift configuration not found")
        
        # Check if the configuration exists
        if request.shift_code not in config.shift_configurations:
            raise HTTPException(
                status_code=404, 
                detail=f"Shift configuration with code '{request.shift_code}' not found"
            )
        
        # Delete the configuration
        del config.shift_configurations[request.shift_code]
        
        # Save the updated configuration
        config.updated_at = get_this_moment()
        await config.save()
        
        # Clear the cache to ensure fresh data is loaded next time
        ShiftConfigHelper.clear_cache(request.client_company_id)
        
        return {"status": "success", "message": "Shift configuration deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting shift configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get-shift-configs/{client_company_id}", response_model=dict)
async def get_shift_configs(client_company_id: str, current_user=Depends(get_current_user)):
    """Get all shift configurations for a project"""
    try:
        # Get the project's shift configuration
        config = await Shift.get_shift_info_for_project(client_company_id)
        if not config:
            raise HTTPException(status_code=404, detail="Project shift configuration not found")
        
        # Convert the configurations to a list of dictionaries
        configs = {}
        for code, shift_config in config.shift_configurations.items():
            configs[code] = shift_config.model_dump()
        
        return {"status": "success", "configurations": configs}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting shift configurations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

