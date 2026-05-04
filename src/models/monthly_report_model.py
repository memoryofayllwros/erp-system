from typing import Optional

from beanie import Document
from dotenv import load_dotenv
from pymongo import IndexModel

load_dotenv()


class MonthlyReport(Document):
    month: str  # 2025-11
    monthly_report_id: Optional[str] = None
    deleted_at: Optional[str] = None

    class Settings:
        name = "monthly_report_collection"
        indexes = [
            IndexModel(
                [("month", 1)],
                unique=True,
                partialFilterExpression={"deleted_at": {"$eq": None}},
            )
        ]

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    async def update_monthly_report_id(cls, month: str, monthly_report_id: str):
        existing_report = await cls.find_one(cls.month == month, cls.deleted_at == None)

        if existing_report:
            await existing_report.set({cls.monthly_report_id: monthly_report_id})
        else:
            await cls(month=month, monthly_report_id=monthly_report_id).insert()

    @classmethod
    async def create_monthly_report_id(cls, month: str, monthly_report_id: str):
        existing_report = await cls.find_one(cls.month == month, cls.deleted_at == None)

        if existing_report:
            return {
                "status": "exists",
                "message": f"📅 月份 {month} 已經有報表啦，唔使再加喇。",
                "data": existing_report,
            }

        new_report = cls(month=month, monthly_report_id=monthly_report_id)

        await new_report.insert()

        return {
            "status": "success",
            "message": f"✅ 已為 {month} 建立月結報表。",
            "data": new_report,
        }
