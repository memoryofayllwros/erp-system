import asyncio
import logging
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.relativedelta import relativedelta
from pymongo.errors import (AutoReconnect, ConnectionFailure,
                            ServerSelectionTimeoutError)

from src.models.monthly_report_model import MonthlyReport
from src.pdf_templates.monthly_checklist_pdf import \
    generate_monthly_expense_checklist
from infrastructure.database.database_connection import get_grid_fs, init
from src.utils.datetime_standarization_helpers import get_this_day, HK_TZ



async def generate_monthly_report(expense_month):
    for attempt in range(MAX_RETRIES):
        try:
            pdf_content = await generate_monthly_expense_checklist(expense_month)

            if isinstance(pdf_content, str):
                logging.warning(f"[{expense_month}] Skipped: {pdf_content}")
                return

            report_filename = f"{expense_month}_monthly_report.pdf"

            # Get GridFS connection
            try:
                grid_fs = await get_grid_fs()
                logging.info("GridFS connection established for monthly report upload.")
            except Exception as e:
                logging.error(f"Failed to get GridFS connection: {str(e)}")
                return

            grid_fs = await get_grid_fs()

            monthly_report_id = await grid_fs.upload_from_stream(
                filename=report_filename, source=pdf_content
            )

            await MonthlyReport.update_monthly_report_id(
                expense_month, str(monthly_report_id)
            )
            logging.info(
                f"Successfully updated monthly report for {expense_month}, ID: {monthly_report_id}."
            )
            return

        except (AutoReconnect, ConnectionFailure, ServerSelectionTimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                logging.warning(
                    f"Database connection error (attempt {attempt + 1}/{MAX_RETRIES}): {str(e)}"
                )
                await asyncio.sleep(RETRY_DELAY)
            else:
                logging.error(
                    f"Failed to generate monthly report after {MAX_RETRIES} attempts: {str(e)}"
                )
                raise
        except Exception as e:
            logging.error(f"Unexpected error generating monthly report: {str(e)}")
            raise


async def schedule_monthly_report():
    try:
        today = get_this_day()
        this_month = today
        month = this_month.strftime("%Y-%m")  # e.g., "2025-03"

        await generate_monthly_report(month)
    except Exception as e:
        logging.error(f"Error in schedule_monthly_report: {str(e)}")


scheduler = BackgroundScheduler(timezone=HK_TZ)


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            lambda: asyncio.create_task(schedule_monthly_report()),
            CronTrigger(hour=21, minute=15, timezone=HK_TZ),
            #   CronTrigger(day=1, hour=12, minute=0, timezone=HKT)  # 🗓 1st of each month at 12:00 PM HKT
        )
        scheduler.start()
        logging.info("📅 Scheduler started to run on the 1st of each month at noon.")
    else:
        logging.info("🕒 Scheduler is already running.")
