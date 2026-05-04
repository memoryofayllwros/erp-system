import logging
import os
import re
from decimal import Decimal
from io import BytesIO
from typing import List

from bson import ObjectId
from openpyxl import Workbook

from src.models.attendance_record_model import AttendanceRecord
from src.models.project_model import Project
from src.models.user_model import User
from src.pdf_templates.payslip_xlsx.payslip_helpers import (PayslipDayEntry,
                                                            _ensure_31_days)
from src.pdf_templates.payslip_xlsx.project_payslip_summary_xlsx import (
    ProjectSummaryItem, add_summary_sheet_to_workbook)
from src.pdf_templates.payslip_xlsx.single_worker_payslip_xlsx import \
    _populate_payslip_sheet
from infrastructure.database.database_connection import get_grid_fs

base_url = os.getenv("BASE_URL")


# Multi-project payslip generator: produce one XLSX per project, with one sheet per worker
async def generate_all_project_payslip_xlsx(
    *,
    output_dir: str,
    year: int,
    month: int,
) -> List[str]:

    grouped_day_entries = await AttendanceRecord.get_grouped_day_entries_for_payslip(
        month=month, year=year
    )
    logging.info(f"grouped_day_entries: {grouped_day_entries}")

    os.makedirs(output_dir, exist_ok=True)
    saved_paths: List[str] = []

    for project_group in grouped_day_entries:
        project_id = project_group["project_id"]
        logging.info(f"project_id under grouped_day_entries: {project_id}")
        project_info = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        if not project_info:
            continue

        project_code = project_info.project_code

        project_location = project_info.project_title

        wb = Workbook()
        summary_items: List[ProjectSummaryItem] = []

        # Iterate workers; use the default active sheet for the first worker, then create sheets
        first_worker = True
        for worker_group in project_group.get("workers", []):
            worker_id = worker_group["worker_id"]
            worker_info = await User.find_one(
                User.id == ObjectId(worker_id), User.deleted_at == None
            )
            if not worker_info:
                continue

            employee_chinese_name = worker_info.chinese_name or ""
            employee_english_name = worker_info.english_name or ""
            country_code = worker_info.country_code or ""
            mobile = worker_info.mobile or ""
            id_no = worker_info.national_id_no or ""
            address = worker_info.address or ""
            base_daily_salary = (
                worker_info.base_daily_salary
                if worker_info.base_daily_salary is not None
                else Decimal(1000)
            )  # standard日薪工資

            # banker and bank account no (if present)
            try:
                banker = getattr(worker_info, "banker", "") or ""
            except Exception:
                banker = ""
            bank_account_no = (
                worker_info.banking_card.bank_account_no
                if getattr(worker_info, "banking_card", None)
                else ""
            )

            ws = wb.active if first_worker else wb.create_sheet()
            ws.title = employee_chinese_name or employee_english_name or str(worker_id)
            first_worker = False

            # Build day entries
            entries = worker_group.get("entries", [])
            day_entries: List[PayslipDayEntry] = []
            for entry in entries:
                day = int(entry.get("day", 0))
                am_worked = bool(entry.get("morning", False))
                pm_worked = bool(entry.get("afternoon", False))
                raw_ot = entry.get("ot", "0")
                try:
                    ot_hours = Decimal(str(raw_ot))
                except Exception:
                    ot_hours = Decimal(0)
                day_entries.append(
                    PayslipDayEntry(
                        day=day,
                        am_worked=am_worked,
                        pm_worked=pm_worked,
                        ot_hours=ot_hours,
                    )
                )

            normalized_entries = _ensure_31_days(day_entries, year, month)

            _populate_payslip_sheet(
                ws,
                employee_chinese_name=employee_chinese_name,
                employee_english_name=employee_english_name,
                employee_code=mobile,
                id_number=id_no,
                country_code=country_code,
                phone=(
                    f"+{country_code}-{mobile}" if country_code and mobile else mobile
                ),
                address=address,
                banker=banker,
                bank_account_no=bank_account_no,
                project_location=project_location,
                year=year,
                month=month,
                normalized_entries=normalized_entries,
                base_daily_salary=base_daily_salary,
                over_65=bool(getattr(worker_info, "over_65", False)),
                hourly_rate=worker_info.hourly_rate,
            )

            # Prepare summary item for this worker
            summary_items.append(
                ProjectSummaryItem(
                    employee_chinese_name=employee_chinese_name,
                    employee_english_name=employee_english_name,
                    employee_code=mobile,
                    banker=banker,
                    bank_account_no=bank_account_no,
                    id_number=id_no,
                    over_65=bool(getattr(worker_info, "over_65", False)),
                    base_daily_salary=base_daily_salary,
                    day_entries=normalized_entries,
                    allowances=[],
                    sheet_name=ws.title,  # Add the sheet name for hyperlink
                    bonus=None,  # Add bonus field, defaulting to None
                )
            )

        # Add Summary sheet at the end
        try:
            add_summary_sheet_to_workbook(
                wb,
                year=year,
                month=month,
                items=summary_items,
                sheet_title="Summary",
                project_location=project_location,
            )
        except Exception:
            # Safeguard: do not fail the whole export if summary has issues
            pass

        # Save workbook to bytes buffer
        buffer = BytesIO()
        wb.save(buffer)
        xlsx_bytes = buffer.getvalue()
        buffer.close()

        # Upload to GridFS and update Project.monthly_attendance_ids
        try:
            grid_fs = await get_grid_fs()
            filename = f"payslip_{project_code}_{year}{str(month).zfill(2)}.xlsx"
            file_id = await grid_fs.upload_from_stream(
                filename,
                xlsx_bytes,
                metadata={
                    "project_id": str(project_id),
                    "year": year,
                    "month": month,
                    "type": "monthly_attendance",
                    "format": "xlsx",
                },
            )
            # Atomically upsert the (year, month) entry without replacing the entire array
            try:
                ok = await Project.upsert_single_month_attendance(
                    project_id=str(project_id),
                    month=month,
                    year=year,
                    file_id=str(file_id),
                )
                if not ok:
                    logging.error(
                        f"Upsert of monthly_attendance_ids failed for project {project_id} ({year}-{month})"
                    )
            except Exception as e:
                logging.error(
                    f"Failed to upsert monthly_attendance_ids for project {project_id}: {e}"
                )
        except Exception as e:
            logging.error(
                f"Failed to upload payslip XLSX to GridFS for project {project_code}: {e}"
            )

        # Also write the XLSX to local filesystem for convenience
        file_name = f"payslip_{project_code}_{year}{str(month).zfill(2)}.xlsx"
        output_path = os.path.join(output_dir, file_name)
        try:
            with open(output_path, "wb") as f:
                f.write(xlsx_bytes)
        except Exception as e:
            logging.error(f"Failed to save payslip XLSX locally at {output_path}: {e}")
        saved_paths.append(output_path)

    return saved_paths
