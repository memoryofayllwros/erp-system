import logging
import os

from src.models.project_model import Project
from src.pdf_templates.payslip_xlsx.payslip_generator import \
    generate_all_project_payslip_xlsx
from infrastructure.database.database_connection import get_grid_fs
from src.utils.standardization_helpers import validate_mobile_from_whatsapp

base_url = os.getenv("BASE_URL")


async def read_monthly_payslip_by_chatbot(sender: str, year: int, month: int) -> str:
    try:
        sender_info = await validate_mobile_from_whatsapp(sender)
        sender_name = (
            sender_info.english_name
            if sender_info.english_name
            else sender_info.chinese_name
        )
        # Normalize input types
        year = int(year)
        month = int(month)
        # Accept 2-digit year input like 25 -> 2025
        if year < 100:
            year += 2000

        try:
            tmp_dir = f"/tmp/payslip_{year}_{str(month).zfill(2)}"
            os.makedirs(tmp_dir, exist_ok=True)
            saved_paths = await generate_all_project_payslip_xlsx(
                output_dir=tmp_dir, year=year, month=month
            )
            # Cleanup temporary files
            try:
                for p in saved_paths or []:
                    if p and os.path.exists(p):
                        os.remove(p)
            except Exception:
                pass
            try:
                if os.path.isdir(tmp_dir):
                    os.rmdir(tmp_dir)
            except Exception:
                pass
        except Exception as gen_err:
            logging.warning(f"Payslip generation step skipped/failed: {gen_err}")

        # Fetch all non-deleted projects
        all_projects = await Project.find(Project.deleted_at == None).to_list()

        results = []
        grid_fs = await get_grid_fs()
        for project in sorted(all_projects, key=lambda p: str(p.project_code)):
            try:
                for entry in project.monthly_attendance_ids or []:
                    entry_year = getattr(entry, "year", None)
                    entry_month = getattr(entry, "month", None)
                    if int(entry_year) == year and int(entry_month) == month:
                        project_code_str = project.project_code
                        file_id_str = getattr(entry, "monthly_attendance_id", None)
                        # Verify file exists in GridFS to avoid broken links
                        try:
                            from bson import ObjectId

                            object_id = ObjectId(file_id_str)
                            grid_out = await grid_fs.open_download_stream(object_id)
                            # Read a small chunk to validate existence/content
                            _chk = await grid_out.read(1)
                            if not _chk:
                                continue
                        except Exception:
                            continue

                        payslip_url = f"{base_url}/{project_code_str}/payslip/{year}/{str(month).zfill(2)}/download-xlsx"
                        results.append(
                            f"📍 {project_code_str}（{project.project_title}）\n🗓️ 糧單記錄/payslip: {payslip_url}\n"
                        )  # 出勤記錄: {project.attendance_record_url}\n")
                        break

            except Exception:
                continue

        if not results:
            return f"⚠️ Currently, there are no payslips available for any projects for {month}/{year}.\n{year}年{month}月 暫時未有任何項目的薪金表。\n"

        lines = "\n".join(results)
        return (
            f"Thank you, {sender_name}!\n"
            f"Here are the project payslip download links for {month}/{year}.\n以下係 {year} 年 {month} 月嘅項目薪金表下載連結: \n\n"
            f"{lines}"
        )

    except Exception as e:
        logging.error(f"Error in list_payslip_urls_by_chatbot: {str(e)}")
        return f"⚠️ 出錯啦: \n\nAn error occurred:{str(e)}"
