import base64
import logging
import os
import tempfile
from datetime import date, datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

try:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import nsdecls
    from docx.oxml.shared import OxmlElement, qn
    from docx.shared import Inches, Pt
    from docxtpl import DocxTemplate, InlineImage
except ImportError:
    logging.warning("docxtpl library not installed. Install with: pip install docxtpl")
    DocxTemplate = None
    InlineImage = None


async def generate_contract_word_document(
    is_daily_contract: bool,
    worker_id: str,
    position: str,
    contract_no: str,  # display contract no based on create_default_contract_no() function, then user can edit it if needed
    contract_issue_date: date,
    contract_start_date: date,
    salary_amount: float,
    project_id: str,
    probation_period: int,  # days
    output_path: Optional[str] = None,
    **kwargs,
) -> str:
    """Generate a complete Word document from scratch"""

    if not project_id:
        raise ValueError("Project ID is required")

    # Get project info
    from bson import ObjectId

    from src.models.project_model import Project

    project_info = await Project.find_one(
        Project.id == ObjectId(project_id), Project.deleted_at == None
    )
    if not project_info:
        raise ValueError("Project not found")

    # Build working location string
    location_parts = []
    if project_info.project_location.building:
        location_parts.append(project_info.project_location.building)
    if project_info.project_location.street:
        location_parts.append(project_info.project_location.street)
    if project_info.project_location.district:
        location_parts.append(project_info.project_location.district)
    if project_info.project_location.region:
        location_parts.append(project_info.project_location.region)

    working_location = ", ".join(location_parts) if location_parts else "待定"

    # Get worker info
    from src.models.user_model import User

    worker_info = await User.find_one(
        User.id == ObjectId(worker_id), User.deleted_at == None
    )
    if not worker_info:
        raise ValueError("Worker not found")

    worker_name = worker_info.chinese_name
    national_id_no = worker_info.national_id_no
    gender = worker_info.gender
    gender_info = "*男士/女士" if gender == "M" else "男士/*女士"
    mobile = worker_info.mobile

    banking_card_no = (
        worker_info.banking_card.bank_account_no
        if worker_info.banking_card
        else "未提供"
    )

    # Use the correct template file path
    if is_daily_contract:
        template_path = os.path.join(
            os.path.dirname(__file__), "daily_employee_contract.docx"
        )
    else:
        template_path = os.path.join(
            os.path.dirname(__file__), "monthly_employee_contract.docx"
        )

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    doc = DocxTemplate(template_path)

    # Complete context dictionary with all placeholders
    context = {
        "worker_name": worker_name,
        "national_id_no": national_id_no,
        "contract_no": contract_no,
        "gender": gender_info,
        "worker_mobile": mobile,
        "banking_card_no": banking_card_no,
        "salary_amount": salary_amount,
        "start_date": contract_start_date.strftime("%d/%m/%Y"),
        "issue_date": contract_issue_date.strftime("%d/%m/%Y"),
        "today_date": get_this_moment().strftime("%d/%m/%Y"),
        "working_location": working_location,
        "position": position,
        "probation_period": probation_period,
        "project_address": (
            project_info.project_title if project_info.project_title else "待定"
        ),
    }

    # Render the template - this replaces all placeholders with actual values
    doc.render(context)

    # Create a temporary file if no output_path is provided
    if output_path is None:
        # Create a temporary file with .docx extension
        temp_fd, output_path = tempfile.mkstemp(
            suffix=".docx", prefix="employee_contract_"
        )
        os.close(temp_fd)  # Close the file descriptor since we only need the path

    # Save the rendered document
    doc.save(output_path)

    return output_path
