import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from beanie import Document
from beanie.operators import Set
from bson import ObjectId
from dotenv import load_dotenv
from pydantic import BaseModel, Field, computed_field, field_validator

from src.models.project_count_model import ProjectCounter
from src.utils.datetime_standarization_helpers import get_this_moment
load_dotenv()

base_url = os.getenv("BASE_URL")
google_maps_url = os.getenv("GOOGLE_MAPS_URL")
google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")


class ProjectGPSLocation(BaseModel):
    lat: str
    lon: str
    location_name: str
    reference_buildings: Optional[List[Dict[str, Union[str, float]]]] = None

    @computed_field
    @property
    def location_gps_url(self) -> str:
        """Generate Google Maps URL for this location"""
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"


class ProjectLocation(BaseModel):
    region: Optional[str] = None
    district: Optional[str] = None
    street: Optional[str] = None
    building: Optional[str] = None


class MonthlyAttendance(BaseModel):
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=1900, description="Year")
    monthly_attendance_id: str

    @field_validator("month")
    def validate_month(cls, v):
        if not 1 <= v <= 12:
            raise ValueError("Month must be between 1 and 12")
        return v

    @field_validator("monthly_attendance_id")
    def validate_attendance_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Monthly attendance ID cannot be empty")
        return v.strip()


class Project(Document):
    project_code: str
    project_title: str
    client_company_id: Optional[str] = None
    project_location: Optional[ProjectLocation] = None
    project_gps_location: Optional[List[ProjectGPSLocation]] = None

    monthly_attendance_ids: Optional[List[MonthlyAttendance]] = None
    client_name: Optional[str] = None

    attendance_record_id: Optional[str] = None
    
    created_by: str #connect to user_collection

    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "project_collection"

    class Config:
        arbitrary_types_allowed = True

    @field_validator("monthly_attendance_ids")
    def validate_attendance_ids(cls, v):
        if v is None:
            return []

        valid_entries = []
        for item in v:
            if item is not None:
                try:
                    if isinstance(item, dict):
                        valid_entries.append(MonthlyAttendance(**item))
                    elif isinstance(item, MonthlyAttendance):
                        valid_entries.append(item)
                except Exception as e:
                    logging.warning(
                        f"Invalid attendance data skipped: {item}, error: {e}"
                    )
                    continue
        return valid_entries

    @computed_field
    @property
    def attendance_record_url(self) -> Optional[str]:
        if not self.attendance_record_id:
            return None
        return f"{base_url}/project/attendance-record/{self.attendance_record_id}/preview/"

    @classmethod
    async def get_project_code_from_id(cls, project_id: str):
        if not project_id:
            return None
        try:
            project = await cls.find_one(
                cls.id == ObjectId(project_id), cls.deleted_at == None
            )
            return project.project_code if project else None
        except Exception as e:
            logging.error(f"Error in get_project_code_from_id: {str(e)}")
            return None

    @classmethod
    async def get_project_by_code(cls, project_code: str):
        """Get project by project code"""
        project = await cls.find_one(
            cls.project_code == project_code, cls.deleted_at == None
        )
        return project.model_dump() if project else None

    @classmethod
    async def read_specific_project_function(cls, project_code: str) -> Dict[str, Any]:
        try:
            this_project = await cls.find_one(
                cls.project_code == project_code, cls.deleted_at == None
            )

            if not this_project:
                return {
                    "status": "error",
                    "message": f"❌ 找不到項目編號 {project_code} 的資料。\nNo project data found for project number {project_code}.",
                }

            project_title = this_project.project_title
            
            # Debug logging
            logging.info(f"🔍 Debug - Project {project_code}:")
            logging.info(f"🔍 attendance_record_id: {this_project.attendance_record_id}")
            logging.info(f"🔍 base_url: {base_url}")
            logging.info(f"🔍 attendance_record_id type: {type(this_project.attendance_record_id)}")
            logging.info(f"🔍 attendance_record_id bool: {bool(this_project.attendance_record_id)}")
            
            # Check if attendance_record_id exists and is not empty
            if this_project.attendance_record_id and this_project.attendance_record_id.strip():
                # Manually construct the URL to ensure it's correct
                attendance_record_url = f"{base_url}/project/attendance-record/{this_project.attendance_record_id}/preview/"
                logging.info(f"🔍 Constructed URL: {attendance_record_url}")
            else:
                attendance_record_url = "暫無/None yet"
                logging.info(f"🔍 No attendance_record_id found, using default message")

            gps_locations: List[ProjectGPSLocation] = (
                this_project.project_gps_location or []
            )

            gps_locations_str = (
                "\n".join(
                    [
                        f"{i+1}. {loc.location_name}: ({loc.location_gps_url})"
                        for i, loc in enumerate(gps_locations)
                    ]
                )
                if gps_locations
                else "未設置/Not set yet"
            )

            project_location_str = f"{this_project.project_location.region if this_project.project_location.region else ''}, {this_project.project_location.district if this_project.project_location.district else ''}, {this_project.project_location.street if this_project.project_location.street else ''}{', ' + this_project.project_location.building if this_project.project_location.building else ''}"
            message = (
                f"Project title / 項目名稱: {project_title}\n"
                f"Project location / 項目位置: {project_location_str}\n\n"
                f"🗓️ Attendance record / 出勤記錄: {attendance_record_url}\n\n"
                f"📍 GPS location / 打卡點位置: \n{gps_locations_str}\n"
            )

            confirmation_message = f" Here is the project details for {project_code}.\n{project_code} 嘅項目資料如下。\n\n{message}"

            return {
                "status": "success",
                "message": confirmation_message,
                "project_info": this_project,
            }

        except Exception as e:
            logging.error(f"Error fetching project data for {project_code}: {str(e)}")
            return {"status": "error", "message": f"⚠️ {str(e)}"}

    @classmethod
    async def add_project_function(
        cls,
        project_title: str,
        region: str,
        district: str,
        street: str,
        client_name: Optional[str] = None,
        company_user_id: Optional[str] = None,
        building: Optional[str] = None,
    ) -> dict:
        try:
            # Validate input parameters
            if not project_title:
                return {"status": "error", "message": "⚠️ 項目名稱不能為空"}
            
            if not region and not district and not street:
                return {"status": "error", "message": "⚠️ 請至少提供一個地址欄位 (地區/區域/街道)"}
            
            if not company_user_id:
                return {"status": "error", "message": "⚠️ 缺少公司用戶ID (company_user_id)"}
            
            # Get user and client company information
            from src.models.user_model import User
            try:
                user_info = await User.find_one(User.id == ObjectId(company_user_id), User.deleted_at == None)
                if not user_info:
                    return {"status": "error", "message": f"⚠️ 找不到用戶ID: {company_user_id}"}
                
                client_company_id = user_info.client_company_id
                if not client_company_id:
                    return {"status": "error", "message": f"⚠️ 用戶 {company_user_id} 沒有關聯的公司ID"}
            except Exception as e:
                return {"status": "error", "message": f"⚠️ 獲取用戶資訊時出錯: {str(e)}"}
            
            # Get or create project counter
            current_year = get_this_moment().year % 100  # e.g., 2025 -> 25
            try:
                counter = await ProjectCounter.find_one(
                    ProjectCounter.client_company_id == client_company_id, 
                    ProjectCounter.year == current_year
                )
                
                if counter:
                    counter.project_count += 1
                    await counter.save()
                else:
                    counter = ProjectCounter(
                        year=current_year, 
                        project_count=1,
                        client_company_id=client_company_id
                    )
                    await counter.insert()
            except Exception as e:
                return {"status": "error", "message": f"⚠️ 更新項目計數器時出錯: {str(e)}"}

            # Generate project code
            project_number = str(counter.project_count).zfill(3)
            project_code = f"{str(current_year).zfill(2)}{project_number}"

            # Create location object
            location = ProjectLocation(
                region=region if region else None,
                district=district if district else None,
                street=street if street else None,
                building=building if building else None,
            )

            # Create and save new project
            try:
                new_project = cls(
                    project_code=project_code,
                    project_title=project_title,
                    client_company_id=client_company_id,
                    project_location=location,
                    project_gps_location=None,
                    created_by=company_user_id
                )
                await new_project.insert()
            except Exception as e:
                return {"status": "error", "message": f"⚠️ 創建新項目時出錯: {str(e)}"}

            # Format location string for response
            project_location_str = f"{location.region if location.region else ''}, {location.district if location.district else ''}, {location.street if location.street else ''}{', ' + location.building if location.building else ''}"

            # Create success message
            message = f"✅ 成功新增項目！\n項目編號: {project_code}\n項目名稱: {project_title}\n📍 地址: {project_location_str}\n"
            # Add client name information if available
            if client_name:
                message += f"\n主承建商: {client_name}"

            return {
                "status": "success",
                "message": message,
                "new_project": {
                    "project_id": str(new_project.id),
                    "project_code": new_project.project_code,
                    "project_title": new_project.project_title,
                    "client_company_id": new_project.client_company_id,
                    "project_location": new_project.project_location,
                },
            }

        except Exception as e:
            import logging
            logging.error(f"Error in add_project_function: {str(e)}")
            message = f"⚠️ 創建項目時發生錯誤: {str(e)}"
            return {"status": "error", "message": message}

    @classmethod
    async def update_project_function(
        cls,
        project_code: str,
        project_location: Optional[dict] = None,
        client_name: Optional[str] = None,
    ):
        try:
            existing_project = await cls.find_one(
                cls.project_code == project_code, cls.deleted_at == None
            )
            if not existing_project:
                raise ValueError(f"\n⚠️ 系統裡無呢個項目{project_code}。")

            updates = []

            if project_location:
                if (
                    project_location.get("district")
                    and project_location["district"]
                    != existing_project.project_location.district
                ):
                    old_district = (
                        existing_project.project_location.district or "（空）"
                    )
                    existing_project.project_location.district = project_location[
                        "district"
                    ]
                    updates.append(
                        f"項目地區由「{old_district}」更新為「{project_location['district']}」。"
                    )

                if (
                    project_location.get("street")
                    and project_location["street"]
                    != existing_project.project_location.street
                ):
                    old_street = existing_project.project_location.street or "（空）"
                    existing_project.project_location.street = project_location[
                        "street"
                    ]
                    updates.append(
                        f"項目街道由「{old_street}」更新為「{project_location['street']}」。"
                    )

                if (
                    project_location.get("building")
                    and project_location["building"]
                    != existing_project.project_location.building
                ):
                    old_building = (
                        existing_project.project_location.building or "（空）"
                    )
                    existing_project.project_location.building = project_location[
                        "building"
                    ]
                    updates.append(
                        f"項目建築物名稱由「{old_building}」更新為「{project_location['building']}」。"
                    )

            if (
                client_name
                and client_name != existing_project.client_name
            ):
                old_main_constractor = existing_project.client_name or "（空）"
                existing_project.client_name = client_name
                updates.append(
                    f"主承建商由「{old_main_constractor}」更新為「{client_name}」。"
                )

            if not updates:
                raise ValueError(
                    "⚠️ 請提供最少一項要更新嘅資料（項目地址），否則唔需要進行更新。"
                )

            await existing_project.save()

            updates_summary = "\n".join(updates)
            return f"\n✅ 已成功更新編號為{project_code}嘅項目。\n{updates_summary}"

        except Exception as e:
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def update_work_permit_id(cls, project_code: str, work_permit_id: str):
        project = await cls.find_one(
            cls.project_code == project_code, cls.deleted_at == None
        )
        if project:
            await project.update(Set({cls.work_permit_id: str(work_permit_id)}))

    @classmethod
    async def delete_project_function(cls, project_code: str):

        existing_project = await cls.find_one(
            cls.project_code == project_code, cls.deleted_at == None
        )
        if not existing_project:
            raise ValueError(f"No project found with project id {project_code}")

        project_title = existing_project.project_title

        existing_project.deleted_at = get_this_moment()
        await existing_project.save()

        message = f"\n✅ 項目 {project_code}，位於 {project_title}，已經成功🗑️刪除啦～。"
        return message

    @classmethod
    async def delete_project_with_all_related(cls, project_code: str):

        existing_project = await Project.find_one(
            Project.project_code == project_code, Project.deleted_at == None
        )
        if not existing_project:
            raise ValueError(f"No project found with project id {project_code}")

        try:
            project_title = existing_project.project_title
        except AttributeError:
            return f"⚠️ 項目 {project_code} 缺少地點資訊，請檢查資料完整性。"

        existing_project.deleted_at = get_this_moment()
        await existing_project.update()

        message = f"\n✅ 項目 {project_code}，位於 {project_title}，已經成功🗑️刪除啦～。"
        return message

    @classmethod
    async def update_worker_info_id(cls, project_code: str, worker_info_id: str):
        project = await cls.find_one(
            cls.project_code == project_code, cls.deleted_at == None
        )
        if project:
            await project.update(Set({cls.worker_info_id: str(worker_info_id)}))

    @classmethod
    async def get_all_project_locations(cls) -> List[dict]:
        all_project_info = await cls.find(cls.deleted_at == None).to_list()

        project_data = [
            {
                "project_code": str(project.project_code),
                "project_title": project.project_title,
            }
            for project in all_project_info
        ]

        return project_data

    @classmethod
    async def get_all_project_locations_gps(cls) -> List[dict]:

        try:
            all_projects = await cls.find(cls.deleted_at == None).to_list()

            project_locations = []
            for project in all_projects:
                if project.project_gps_location:
                    for gps_location in project.project_gps_location:
                        project_locations.append(
                            {
                                "project_id": str(project.id),
                                "project_code": project.project_code,
                                "lat": float(gps_location.lat),
                                "long": float(
                                    gps_location.lon
                                ),  # Note: using 'long' to match the expected format
                                "location_name": gps_location.location_name,
                            }
                        )

            logging.info(
                f"Retrieved {len(project_locations)} GPS locations from {len(all_projects)} projects"
            )
            return project_locations

        except Exception as e:
            logging.error(f"Error in get_all_project_locations_gps: {str(e)}")
            return []

    @classmethod
    async def update_reminder_summary_id(
        cls, project_code: str, reminder_summary_id: str
    ):
        project = await cls.find_one(
            cls.project_code == project_code, cls.deleted_at == None
        )
        if project:
            await project.update(
                Set({cls.reminder_summary_id: str(reminder_summary_id)})
            )

    @classmethod
    async def update_attendance_record_id(cls, 
                                          project_id: str, 
                                          attendance_record_id: str
                                          ):
        try:
            project = await cls.find_one(
                cls.id == ObjectId(project_id), cls.deleted_at == None
            )
            if not project:
                return {
                    "status": "error",
                    "message": f"⚠️ Project not found with id {project_id}",
                }
            await project.update(Set({cls.attendance_record_id: str(attendance_record_id)}))
            await project.save()
            return {
                "status": "success",
                "message": f"✅ Successfully updated attendance_record_id for project {project_id}",
                "attendance_record_id": str(attendance_record_id),
            }
        except Exception as e:
            logging.error(f"Error in update_attendance_record_id: {str(e)}")
            return f"⚠️ {str(e)}"




    @classmethod
    async def ensure_attendance_record_id_field(cls, project_id: str) -> bool:
        """Ensure the attendance_record_id field exists in the project document.

        Args:
            project_id: The ID of the project to check/update

        Returns:
            bool: True if field exists or was added successfully, False otherwise
        """
        try:
            logging.info(
                f"🔍 Checking if attendance_record_id field exists for project {project_id}"
            )

            # Find the project
            project = await cls.find_one(
                cls.id == ObjectId(project_id), cls.deleted_at == None
            )
            if not project:
                logging.warning(f"⚠️ Project not found: {project_id}")
                return False

            # Check if the field exists
            if hasattr(project, "attendance_record_id"):
                logging.info(
                    f"✅ attendance_record_id field already exists for project {project_id}"
                )
                return True

            # Field doesn't exist, add it with None value
            logging.info(
                f"➕ Adding attendance_record_id field to project {project_id}"
            )
            try:
                await project.update(Set({cls.attendance_record_id: None}))
                logging.info(
                    f"✅ Successfully added attendance_record_id field to project {project_id}"
                )
                return True
            except Exception as add_error:
                logging.error(
                    f"❌ Error adding attendance_record_id field: {str(add_error)}"
                )

                # Try alternative method
                try:
                    collection = cls.get_motor_collection()
                    result = await collection.update_one(
                        {"_id": ObjectId(project_id), "deleted_at": None},
                        {"$set": {"attendance_record_id": None}},
                    )

                    if result and result.modified_count > 0:
                        logging.info(
                            f"✅ Alternative method successful: added attendance_record_id field"
                        )
                        return True
                    else:
                        logging.error(
                            f"❌ Alternative method failed: no documents modified"
                        )
                        return False

                except Exception as alt_error:
                    logging.error(
                        f"❌ Alternative method also failed: {str(alt_error)}"
                    )
                    return False

        except Exception as e:
            logging.error(
                f"❌ Error in ensure_attendance_record_id_field for project {project_id}: {str(e)}"
            )
            return False

    @classmethod
    async def get_attendance_record_id(cls, project_id: str) -> Optional[str]:
        """Get the current attendance_record_id for a project.

        Args:
            project_id: The ID of the project to check

        Returns:
            Optional[str]: The attendance_record_id if found, None otherwise
        """
        try:
            project = await cls.find_one(
                cls.id == ObjectId(project_id), cls.deleted_at == None
            )
            if project:
                attendance_record_id = getattr(project, "attendance_record_id", None)
                logging.info(
                    f"📊 Project {project_id} attendance_record_id: {attendance_record_id}"
                )
                return attendance_record_id
            else:
                logging.warning(f"⚠️ Project not found: {project_id}")
                return None
        except Exception as e:
            logging.error(
                f"❌ Error getting attendance_record_id for project {project_id}: {str(e)}"
            )
            return None

    @classmethod
    async def update_monthly_attendance_ids(
        cls, project_id: str, monthly_attendance_ids: List[MonthlyAttendance]
    ):
        """Update the monthly attendance IDs for a project.

        Args:
            project_id: The ID of the project to update
            monthly_attendance_ids: List of MonthlyAttendance objects containing month, year, and file ID
        """
        project = await cls.find_one(
            cls.id == ObjectId(project_id), cls.deleted_at == None
        )
        if project:
            # Ensure we have a valid list
            if monthly_attendance_ids is None:
                monthly_attendance_ids = []

            # Convert MonthlyAttendance objects to dictionaries for storage
            # Filter out any None values that might have snuck in
            attendance_dicts = [
                attendance.model_dump()
                for attendance in monthly_attendance_ids
                if attendance is not None
            ]

            await project.update(Set({cls.monthly_attendance_ids: attendance_dicts}))
            return True
        return False

    @classmethod
    async def read_all_projects_function(cls):
        try:
            from src.pdf_templates.attendance_record_pdf import \
                generate_attendance_record_pdf

            all_project_info = await cls.find(cls.deleted_at == None).to_list()

            sorted_projects = sorted(all_project_info, key=lambda x: x.project_code)

            project_data = []
            for project in sorted_projects:
                project_info = {
                    "project_id": str(project.id),
                    "project_code": project.project_code,
                    "project_title": project.project_title,
                }
                pdf_file_id = await generate_attendance_record_pdf(
                    project_info["project_id"]
                )
                if pdf_file_id is None:
                    project_info["attendance_record_id"] = None
                    project_info["attendance_record_url"] = None
                else:
                    project_info["attendance_record_id"] = pdf_file_id
                    project_info["attendance_record_url"] = (
                        f"{base_url}/project/attendance-record/{pdf_file_id}/preview/"
                    )

                if project.project_gps_location:
                    project_info["project_location_gps"] = [
                        gps.model_dump() for gps in project.project_gps_location
                    ]

                project_data.append(project_info)

            return project_data

        except Exception as e:
            logging.error(f"Error fetching project data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def read_all_projects_function_by_endpoint(cls):
        try:

            all_project_info = await cls.find(cls.deleted_at == None).to_list()

            # Sort the projects by project_code
            sorted_projects = sorted(all_project_info, key=lambda x: x.project_code)

            project_data = []
            for project in sorted_projects:
                project_info = {
                    "project_id": str(project.id),
                    "project_code": project.project_code,
                    "project_title": project.project_title,
                    "created_at": (
                        project.created_at.isoformat() if project.created_at else None
                    ),
                    "deleted_at": (
                        project.deleted_at.isoformat() if project.deleted_at else None
                    ),
                }

                # Add project location information
                if project.project_location:
                    project_info["project_location"] = {
                        "region": project.project_location.region,
                        "district": project.project_location.district,
                        "street": project.project_location.street,
                        "building": project.project_location.building,
                    }

                # Add GPS locations
                if project.project_gps_location:
                    project_info["project_location_gps"] = [
                        gps.model_dump() for gps in project.project_gps_location
                    ]

                # Add attendance record information
                if project.attendance_record_id:
                    project_info["attendance_record_id"] = project.attendance_record_id
                    project_info["attendance_record_url"] = (
                        f"{base_url}/project/attendance-record/{project.attendance_record_id}/preview/"
                    )

                # Add monthly attendance information
                if project.monthly_attendance_ids:
                    project_info["monthly_attendance_ids"] = [
                        attendance.model_dump()
                        for attendance in project.monthly_attendance_ids
                    ]

                project_data.append(project_info)

            return project_data

        except Exception as e:
            logging.error(f"Error fetching project data: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def add_project_location_gps(
        cls, project_id: str, latitude: str, longitude: str, location_name: str
    ):

        try:

            existing_project = await cls.find_one(
                cls.id == ObjectId(project_id), cls.deleted_at == None
            )
            if not existing_project:
                return {
                    "status": "error",
                    "message": f"No project found with project id {project_id}",
                    "project_info": None,
                }

            # Convert strings to float for validation and comparison
            try:
                lat_float = float(latitude)
                lon_float = float(longitude)
            except (ValueError, TypeError):
                return {
                    "status": "error",
                    "message": "Invalid latitude or longitude format",
                    "project_info": None,
                }

            if not (-90 <= lat_float <= 90):
                return {
                    "status": "error",
                    "message": "Latitude must be between -90 and 90",
                    "project_info": None,
                }

            if not (-180 <= lon_float <= 180):
                return {
                    "status": "error",
                    "message": "Longitude must be between -180 and 180",
                    "project_info": None,
                }

            # Create new GPS location object
            new_gps_location = ProjectGPSLocation(
                lat=latitude,  # Keep as string if that's what your model expects
                lon=longitude,  # Keep as string if that's what your model expects
                location_name=location_name.strip() if location_name else None,
            )

            # Initialize GPS locations list if it doesn't exist
            if not existing_project.project_gps_location:
                existing_project.project_gps_location = []

            # Check if GPS location with same coordinates already exists
            existing_gps_index = None
            for i, gps_loc in enumerate(existing_project.project_gps_location):
                # Convert stored coordinates to float for comparison
                try:
                    stored_lat = float(gps_loc.lat)
                    stored_lon = float(gps_loc.lon)

                    # Use small tolerance for floating point comparison
                    if (
                        abs(stored_lat - lat_float) < 0.000001
                        and abs(stored_lon - lon_float) < 0.000001
                    ):
                        existing_gps_index = i
                        break
                except (ValueError, TypeError):
                    # Skip this GPS location if coordinates can't be converted
                    continue

            if existing_gps_index is not None:
                # GPS location with same coordinates already exists
                existing_gps = existing_project.project_gps_location[existing_gps_index]
                old_name = existing_gps.location_name
                new_name = location_name.strip() if location_name else None

                # Check if the name is the same
                if old_name == new_name:
                    # Same location name already recorded
                    message = f"⚠️ 同樣嘅打卡點位置 (經度: {latitude}, 緯度: {longitude}, 地點名稱: '{old_name}') 已經存在於項目 {existing_project.project_code}:  {existing_project.project_title} ！\n"
                    message += f"same GPS location (latitude: {latitude}, longitude: {longitude}, location name: '{old_name}') already exists in project {existing_project.project_code}: {existing_project.project_title}!"
                    return {
                        "status": "warning",
                        "message": message,
                        "project_info": existing_project.model_dump(exclude={"_id"}),
                        "gps_locations_count": len(
                            existing_project.project_gps_location
                        ),
                    }
                else:
                    # Same coordinates but different name - update the name
                    existing_gps.location_name = new_name
                    message = f"✅ 經度同緯度已經存在於資料庫啦，打卡點位置名稱已經由 '{old_name}' 改為 '{new_name}' 啦！\n"
                    message += f"successfully updated GPS location name from '{old_name}' to '{new_name}'!"
            else:
                # Add new GPS location
                existing_project.project_gps_location.append(new_gps_location)
                message = f"\n✅ Successfully added new GPS location '{location_name}' to project {existing_project.project_code}: {existing_project.project_title}!"
                message += f"\n✅ 成功添加新嘅打卡點位置 '{location_name}' 到項目 {existing_project.project_code}: {existing_project.project_title}！"
            # Save the project
            await existing_project.save()

            data = existing_project.model_dump(exclude={"_id"})

            return {
                "status": "success",
                "message": message,
                "project_info": data,
                "gps_locations_count": len(existing_project.project_gps_location),
            }

        except ValueError as ve:
            message = f"⚠️ {str(ve)}"
            return {"status": "error", "message": message, "error_type": "validation"}
        except Exception as e:
            message = f"⚠️ {str(e)}"
            return {"status": "error", "message": message, "error_type": "unexpected"}

    @classmethod
    async def get_project_gps_locations(cls, project_code: str):

        try:
            if not project_code or not project_code.strip():
                raise ValueError("Project number cannot be empty")

            project = await cls.find_one(
                cls.project_code == project_code.strip(), cls.deleted_at == None
            )

            if not project:
                raise ValueError(
                    f"No active project found with project number {project_code}"
                )

            gps_locations = project.project_gps_location or []

            return {
                "status": "success",
                "message": f"Found {len(gps_locations)} GPS locations for project {project_code}: {project.project_title}!\n搵到 {len(gps_locations)} 個打卡點位置啦！項目編號: {project_code}",
                "gps_locations": [loc.model_dump(exclude={"_id"}) for loc in gps_locations],
                "count": len(gps_locations),
            }

        except ValueError as ve:
            return {"status": "error", "message": f"⚠️ {str(ve)}"}
        except Exception as e:
            return {"status": "error", "message": f"⚠️ {str(e)}"}

    @classmethod
    async def delete_project_gps_location(cls, project_code: str, location_name: str):
        try:
            if not location_name or not location_name.strip():
                raise ValueError("Location name cannot be empty")

            # Find the project first
            project = await cls.find_one(
                cls.project_code == project_code, cls.deleted_at == None
            )

            if not project:
                raise ValueError(
                    f"No active project found with project number {project_code}"
                )

            if not project.project_gps_location:
                raise ValueError("This project has no GPS locations to remove")

            # Filter out the location to be removed
            original_count = len(project.project_gps_location)
            project.project_gps_location = [
                loc
                for loc in project.project_gps_location
                if loc.location_name != location_name
            ]

            if len(project.project_gps_location) == original_count:
                raise ValueError(
                    f"GPS location '{location_name}' not found in this project"
                )

            await project.save()

            message = f"\n✅ Successully deleted GPS location '{location_name}' from project {project_code}: {project.project_title}!"
            message += f"\n✅ 成功從項目 {project_code}: {project.project_title} 刪除打卡點位置 '{location_name}'。"
            return {
                "status": "success",
                "message": message,
                "remaining_locations": len(project.project_gps_location),
            }

        except ValueError as ve:
            return {"status": "error", "message": f"⚠️ {str(ve)}"}
        except Exception as e:
            return {"status": "error", "message": f"⚠️ {str(e)}"}

    @classmethod
    async def list_project_gps_locations_with_urls(cls, project_code: str):

        try:
            if not project_code or not project_code.strip():
                raise ValueError("Project number cannot be empty")

            project = await cls.find_one(
                cls.project_code == project_code.strip(), cls.deleted_at == None
            )

            if not project:
                raise ValueError(
                    f"No active project found with project number {project_code}"
                )

            gps_locations = project.project_gps_location or []

            if not gps_locations:
                return {
                    "status": "success",
                    "message": f"項目編號: {project_code} 搵唔到打卡點位置喎。",
                    "gps_locations": [],
                    "count": 0,
                }

            # Create list with location names and Google Maps URLs
            locations_with_urls = []
            for i, loc in enumerate(gps_locations, 1):
                # Create Google Maps URL
                google_maps_url = f"{google_maps_url}?q={loc.lat},{loc.lon}"

                location_info = {
                    "index": i,
                    "location_name": loc.location_name or "Unnamed Location",
                    "latitude": loc.lat,
                    "longitude": loc.lon,
                    "google_maps_url": google_maps_url,
                }
                locations_with_urls.append(location_info)

            return {
                "status": "success",
                "message": f"搵到 {len(gps_locations)} 個打卡點位置啦！項目編號: {project_code}",
                "gps_locations": locations_with_urls,
                "count": len(gps_locations),
            }

        except ValueError as ve:
            return {"status": "error", "message": f"⚠️ Validation error: {str(ve)}"}
        except Exception as e:
            return {"status": "error", "message": f"⚠️ Error: {str(e)}"}

    @classmethod
    async def upsert_single_month_attendance(
        cls,
        *,
        project_id: str,
        month: int,
        year: int,
        file_id: str,
    ) -> bool:

        try:
            collection = cls.get_motor_collection()

            # 1) Try to update existing element (handle int or string month/year for backward compatibility)
            # Use arrayFilters so we can match both int and string types reliably
            result = await collection.update_one(
                {"_id": ObjectId(project_id), "deleted_at": None},
                {
                    "$set": {
                        "monthly_attendance_ids.$[elem].monthly_attendance_id": str(
                            file_id
                        )
                    }
                },
                array_filters=[
                    {
                        "elem.month": {"$in": [int(month), str(int(month))]},
                        "elem.year": {"$in": [int(year), str(int(year))]},
                    }
                ],
            )

            if result and result.matched_count and result.modified_count:
                return True

            # 2) If not found, push as a new element
            push_result = await collection.update_one(
                {"_id": ObjectId(project_id), "deleted_at": None},
                {
                    "$push": {
                        "monthly_attendance_ids": {
                            "month": int(month),
                            "year": int(year),
                            "monthly_attendance_id": str(file_id),
                        }
                    }
                },
            )
            return bool(push_result and push_result.modified_count)

        except Exception as e:
            logging.error(
                f"Failed to upsert monthly attendance for project {project_id} ({year}-{month}): {e}"
            )
            return False




    @classmethod
    async def get_project_locations_function(cls, project_id: str) -> List[Dict[str, Any]]:
        project = await cls.find_one(cls.id == ObjectId(project_id), cls.deleted_at == None)
        
        locations = []
        for location in project.project_gps_location:
            try:
                location_data = {
                    "lat": location.lat,
                    "lon": location.lon,
                    "location_name": location.location_name,
                }

                # Only add location_gps_url if it exists
                if hasattr(location, "location_gps_url"):
                    location_data["location_gps_url"] = location.location_gps_url

                locations.append(location_data)
            except Exception as e:
                logging.warning(
                    f"Error processing location for project {project_id}: {e}"
                )
                continue

        return {
            "project_id": project_id,
            "project_code": project.project_code,
            "project_title": project.project_title,
            "locations": locations,
        }
