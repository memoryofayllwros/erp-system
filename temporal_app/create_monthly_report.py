from datetime import datetime

from src.models.monthly_report_model import MonthlyReport
from src.utils.datetime_standarization_helpers import get_this_moment

async def check_and_create_new_mr():
    now = get_this_moment()
    current_month = now.strftime("%Y-%m")  # e.g., "2025-05"
    monthly_report_id = f"REP-{current_month.replace('-', '')}"

    result = await MonthlyReport.create_monthly_report_id(
        month=current_month, monthly_report_id=monthly_report_id
    )

    if result["status"] == "success":
        print(f"[✅ 新增報表] {monthly_report_id}")
    else:
        print(f"[ℹ️ 已存在] {result['message']}")
