from fastapi import APIRouter
from src.models.application_and_approval_model import ApplicationAndApproval
from fastapi import Request
from src.models.user_model import User, Role
from src.routes.user_routes import get_current_user
from fastapi import Depends
from fastapi import HTTPException

router = APIRouter()

@router.get("/get-leave-record-by-user-id")
async def get_my_leave_records(current_user: User = Depends(get_current_user)):
    #check if the current user is admin or manager or HR
    #role is a list of strings
    user_id = current_user.id
    if "Manager" in current_user.role or "HR" in current_user.role or "admin" in current_user.role or "Worker" in current_user.role:
        raise HTTPException(status_code=403, detail="Forbidden")
    else:
        return await ApplicationAndApproval.read_my_leave_records_function(user_id)


@router.get("/get-all-leave-records")
async def get_all_leave_records(current_user: User = Depends(get_current_user)):
    #check if the current user is admin or manager or HR
    #role is a list of strings
    if "Manager" in current_user.role or "HR" in current_user.role or "admin" in current_user.role:
        raise HTTPException(status_code=403, detail="Forbidden")
    else:   
        return await ApplicationAndApproval.read_all_leave_records_function()


@router.delete("/delete-leave-record-by-application-id")
async def delete_leave_record_by_application_id(application_id: str, current_user: User = Depends(get_current_user)):
    if "Manager" in current_user.role or "HR" in current_user.role or "admin" in current_user.role:
        raise HTTPException(status_code=403, detail="Forbidden")
    else:
        return await ApplicationAndApproval.delete_leave_application_function(application_id)