from typing import Optional
from datetime import date, datetime
import logging
from decimal import Decimal
import os
from pydantic import Field, field_validator, computed_field
from beanie import Document
from src.utils.datetime_standarization_helpers import get_this_moment

BASE_URL = os.getenv("BASE_URL")

class WorkerProjectContractInfo(Document):
    contract_no: str
    user_id: str
    project_id: str
    is_daily_contract: bool  # True for daily, False for monthly
    salary: str
    position: str
    contract_issue_date: date
    contract_start_date: date
    probation_period: int  # days
    bonus: str
    contract_document_id: Optional[str] = None
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "worker_project_contract_info_collection"

    class Config:
        arbitrary_types_allowed = True

    @field_validator("contract_no")
    @classmethod
    def validate_contract_no_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Contract number cannot be empty")
        return v.strip()

    @computed_field
    @property
    def contract_download_url(self) -> Optional[str]:
        if not self.contract_document_id:
            return None
        return f"{BASE_URL}/contract/{self.contract_document_id}/"

    @computed_field
    @property
    def hourly_rate(self) -> Optional[Decimal]:
        if not self.salary:
            return None
        try:
            logging.info(
                f"Hourly rate: {(Decimal(self.salary) / Decimal(8)).quantize(Decimal('0.00'))}"
            )
            logging.info(f"Salary: {self.salary}")
            return (Decimal(self.salary) / Decimal(8)).quantize(Decimal("0.00"))
        except (ValueError, TypeError, ArithmeticError):
            logging.warning(
                f"Could not calculate hourly rate for salary: {self.salary}"
            )
            return None


    @classmethod
    async def create_default_contract_no(cls, is_daily_contract: bool, project_id: str):

        # Find users who have the specified project_id in their worker_projects list
        workers_of_one_project = await cls.find(
            {"worker_projects.project_id": project_id, "deleted_at": None}
        ).to_list()
        logging.info(f"Workers of one project: {workers_of_one_project}")

        workers_counts = len(workers_of_one_project)
        contract_type_str = "WOR" if is_daily_contract else "STA"

        from bson import ObjectId

        from src.models.project_model import Project

        project_info = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        logging.info(f"Project info: {project_info}")
        if not project_info:
            raise ValueError("Project not found")
        project_contract_prefix = (
            project_info.project_contract_prefix
            if project_info.project_contract_prefix
            else ""
        )

        # Generate unique contract number
        base_contract_no = (
            f"{project_contract_prefix}/{contract_type_str}/{workers_counts+1:04d}"
        )
        contract_no = base_contract_no

        # Check if contract number already exists and find next available number
        counter = 1
        while await cls.check_contract_no_exists(contract_no):
            counter += 1
            contract_no = f"{project_contract_prefix}/{contract_type_str}/{workers_counts+counter:04d}"

        return contract_no

    @classmethod
    async def check_contract_no_exists(cls, contract_no: str) -> bool:
        """
        Check if a contract number already exists in the database
        """
        try:
            # Search for users who have this contract number in their worker_projects
            existing_contract = await cls.find_one(
                {"worker_projects.contract_no": contract_no, "deleted_at": None}
            )
            return existing_contract is not None
        except Exception as e:
            logging.error(f"Error checking contract number existence: {str(e)}")
            return False



    @classmethod
    async def create_employee_contract_function(
        cls,
        worker_id: str,
        position: str,
        is_daily_contract: bool,
        contract_no: str,
        contract_issue_date: date,
        probation_period: int,  # days
        contract_start_date: date,
        salary_amount: str,
        project_id: str,
        bonus: str,
    ):
        try:

            from io import BytesIO

            from bson import ObjectId

            from src.pdf_templates.employee_contract.employee_contract_docx import \
                generate_contract_word_document
            from infrastructure.database.database_connection import get_grid_fs

            # Find the worker by national_id_no
            worker_info = await cls.find_one(
                cls.id == ObjectId(worker_id), cls.deleted_at == None
            )

            if not worker_info:
                return f"⚠️ 找不到工人資料，工人ID: {worker_id}"

            # Check if contract number already exists
            if await cls.check_contract_no_exists(contract_no):
                return f"⚠️ 合約編號 {contract_no} 已存在，請使用不同的合約編號"

            # contract_type is now a boolean, no validation needed

            # Convert salary_amount from string to float
            try:
                salary_amount_float = float(salary_amount.replace(",", ""))
                if salary_amount_float <= 0:
                    return f"⚠️ 薪資金額必須大於0: {salary_amount}"
            except (ValueError, TypeError):
                return f"⚠️ 無效的薪資金額格式: {salary_amount}"

            # Initialize variables for cleanup tracking
            generated_contract_path = None
            is_temp_file = False

            # Generate contract document if not provided
            if not generated_contract_path:
                # Generate contract using template
                try:
                    generated_contract_path = await generate_contract_word_document(
                        is_daily_contract=is_daily_contract,
                        worker_id=worker_id,
                        position=position,
                        contract_no=contract_no,
                        contract_issue_date=contract_issue_date,
                        contract_start_date=contract_start_date,
                        bonus=bonus,
                        salary_amount=salary_amount_float,
                        project_id=project_id,
                        probation_period=probation_period,
                    )
                    is_temp_file = True  # Mark as temporary file for cleanup
                except Exception as gen_error:
                    logging.error(f"Error generating contract: {str(gen_error)}")
                    return f"⚠️ 生成合約文件時發生錯誤: {str(gen_error)}"

            try:
                # Read the contract Word document as binary data
                if not os.path.exists(generated_contract_path):
                    return f"⚠️ 合約文件不存在: {generated_contract_path}"

                with open(generated_contract_path, "rb") as contract_file:
                    contract_binary_data = contract_file.read()

                grid_fs = await get_grid_fs()

                safe_contract_no = "".join(
                    c for c in contract_no if c.isalnum() or c in (" ", "-", "_")
                ).rstrip()
                contract_type_str = "daily" if is_daily_contract else "monthly"
                filename = (
                    f"contract_{contract_type_str}_{project_id}_{safe_contract_no}.docx"
                )

                contract_stream = BytesIO(contract_binary_data)
                contract_gridfs_id = await grid_fs.upload_from_stream(
                    filename=filename, source=contract_stream
                )

                worker_project_match = WorkerProjectContractInfo(

                    contract_document_id=str(contract_gridfs_id),
                    position=position,
                    is_daily_contract=is_daily_contract,
                    contract_no=contract_no,
                    contract_issue_date=contract_issue_date,
                    probation_period=probation_period,
                    contract_start_date=contract_start_date,
                    bonus=bonus,
                    salary=salary_amount,
                    project_id=project_id,
                )

                if worker_info.worker_projects is None:
                    worker_info.worker_projects = []

                worker_info.worker_projects.append(worker_project_match)
                await worker_info.save()

                contract_type_str = "日薪" if is_daily_contract else "月薪"
                return f"✅ 成功為工人 {worker_info.english_name} ({worker_info.chinese_name}) 創建{contract_type_str}合約 {contract_no}，GridFS ID: {contract_gridfs_id}"

            finally:
                if (
                    is_temp_file
                    and generated_contract_path
                    and os.path.exists(generated_contract_path)
                ):
                    try:
                        os.remove(generated_contract_path)
                        logging.info(
                            f"Cleaned up generated contract file: {generated_contract_path}"
                        )
                    except Exception as cleanup_error:
                        logging.warning(
                            f"Failed to clean up generated file {generated_contract_path}: {cleanup_error}"
                        )

        except Exception as e:
            logging.error(f"Error creating employee contract: {str(e)}")
            return f"⚠️ 發生錯誤: {str(e)}"

    @classmethod
    async def get_contract_document(cls, contract_gridfs_id: str):
        """
        Retrieve a contract document from GridFS by its ID
        """
        try:
            from bson import ObjectId

            from infrastructure.database.database_connection import get_grid_fs

            try:
                object_id = ObjectId(contract_gridfs_id)
            except Exception as e:
                logging.error(f"Invalid ObjectId format: {contract_gridfs_id}")
                return None, f"Invalid contract ID format: {str(e)}"

            grid_fs = await get_grid_fs()

            # Try to open the file
            try:
                grid_out = await grid_fs.open_download_stream(object_id)
                content = await grid_out.read()

                if not content:
                    return None, "Contract document not found or empty"

                # Get filename and metadata
                filename = (
                    grid_out.filename
                    if hasattr(grid_out, "filename")
                    else f"contract_{contract_gridfs_id}.docx"
                )
                metadata = grid_out.metadata if hasattr(grid_out, "metadata") else {}

                return {
                    "content": content,
                    "filename": filename,
                    "metadata": metadata,
                }, None

            except Exception as e:
                logging.error(f"Error reading contract from GridFS: {str(e)}")
                return None, f"Error retrieving contract: {str(e)}"

        except Exception as e:
            logging.error(f"Error in get_contract_document: {str(e)}")
            return None, f"Unexpected error: {str(e)}"

    @classmethod
    async def delete_contract_document(cls, contract_gridfs_id: str):
        """
        Delete a contract document from GridFS by its ID
        """
        try:
            from bson import ObjectId

            from infrastructure.database.database_connection import get_grid_fs

            try:
                object_id = ObjectId(contract_gridfs_id)
            except Exception as e:
                logging.error(f"Invalid ObjectId format: {contract_gridfs_id}")
                return f"Invalid contract ID format: {str(e)}"

            # Get GridFS instance
            grid_fs = await get_grid_fs()

            # Delete the file
            try:
                await grid_fs.delete(object_id)
                return f"✅ Contract document {contract_gridfs_id} deleted successfully"
            except Exception as e:
                logging.error(f"Error deleting contract from GridFS: {str(e)}")
                return f"⚠️ Error deleting contract: {str(e)}"

        except Exception as e:
            logging.error(f"Error in delete_contract_document: {str(e)}")
            return f"⚠️ Unexpected error: {str(e)}"
