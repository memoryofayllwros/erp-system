import logging
from datetime import datetime

import pytz
from bson import ObjectId

from src.models.attendance_record_model import AttendanceRecord
from src.models.project_model import Project
from src.utils.standardization_helpers import validate_mobile_from_whatsapp
from src.utils.datetime_standarization_helpers import get_this_day, HK_TZ


async def read_today_attendance_stituations_function(project_id: str, date_obj=None):
    try:
        project = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        if not project:
            return f"❌ Project not found with ID: {project_id}"

        # If no date is provided, use today's date in HK timezone
        if date_obj is None:
            date_obj = get_this_day()

        # Get today's attendance records for the project
        today_attendance = await AttendanceRecord.get_today_attendance_for_project(
            project_id, date_obj
        )

        if not today_attendance:
            return f"📍 *{project.project_code}: {project.project_title}*\n今日無出勤記錄。\n\nNo attendance records today.\n"

        # Format the response
        summary_response = f"📍 *{project.project_code}: {project.project_title}*\n"  # ascending order by project_code
        summary_response += f"👥 該項目今日出勤人數:\n\nToday's attendance count for this project: {len(today_attendance)}\n"

        # Group workers by status
        completed_workers = []
        pending_workers = []
        no_attendance_workers = []

        for worker in today_attendance:
            if worker["completed_shifts"] > 0 and worker["pending_shifts"] == 0:
                completed_workers.append(worker)
            elif worker["pending_shifts"] > 0:
                pending_workers.append(worker)
            else:
                no_attendance_workers.append(worker)

        detailed_response = ""
        # Add completed workers section
        if completed_workers:
            detailed_response += "✅ *已完成班次:\n\nShifts completed*\n"
            for index, worker in enumerate(completed_workers, 1):
                detailed_response += f"{index}. {worker['english_name'] if worker['english_name'] is not None else worker['payee_name']}\n"
                for shift in worker["shifts"]:
                    if shift["status"] == "completed":
                        detailed_response += f"  - {shift['shift_type'].upper()}: {shift['check_in_time']} - {shift['check_out_time']}"
                        if shift["is_late_check_in"]:
                            detailed_response += " ⚠️ 遲到/late"
                        if shift["is_early_check_out"]:
                            detailed_response += " ⚠️ 早退/Early check-out"
                        # Add image indicators for check-in and check-out
                        if shift.get("check_in_method") == "image":
                            detailed_response += " (圖片/Image)"
                        if shift.get("check_out_method") == "image":
                            detailed_response += "(圖片/Image)"
                        detailed_response += "\n"

        if pending_workers:
            detailed_response += "🔄 *待簽退/Waiting for check out:*\n"
            for index, worker in enumerate(pending_workers, 1):
                detailed_response += f"{index}. {worker['english_name'] if worker['english_name'] is not None else worker['payee_name']}\n"
                for shift in worker["shifts"]:
                    if shift["status"] == "pending":
                        # Check if check-in was done via image
                        check_in_indicator = ""
                        if shift.get("check_in_method") == "image":
                            check_in_indicator = "圖片/Image"

                        if check_in_indicator:
                            detailed_response += f"  - {shift['shift_type'].upper()}: 已{check_in_indicator}簽到/Already check in: {shift['check_in_time']} (待簽退)\n"
                        else:
                            detailed_response += f"  - {shift['shift_type'].upper()}: 已簽到/Already check in: {shift['check_in_time']} (待簽退)\n"
                detailed_response += "\n"

        if no_attendance_workers:
            detailed_response += "❌ *今日無出勤/No attendance:*\n"
            for index, worker in enumerate(no_attendance_workers, 1):
                detailed_response += f"{index}. {worker['english_name'] if worker['english_name'] is not None else worker['payee_name']}\n"
            detailed_response += "\n"

        # Add summary statistics
        total_completed_shifts = sum(
            worker["completed_shifts"] for worker in today_attendance
        )
        total_pending_shifts = sum(
            worker["pending_shifts"] for worker in today_attendance
        )

        workers_checked_in = len(
            [
                w
                for w in today_attendance
                if any(s.get("check_in_time") for s in w["shifts"])
            ]
        )
        workers_checked_out = len(
            [
                w
                for w in today_attendance
                if any(s.get("check_out_time") for s in w["shifts"])
            ]
        )

        # Count workers who were late or left early
        workers_late = len(
            [
                w
                for w in today_attendance
                if any(s.get("is_late_check_in") for s in w["shifts"])
            ]
        )
        workers_early_out = len(
            [
                w
                for w in today_attendance
                if any(s.get("is_early_check_out") for s in w["shifts"])
            ]
        )

        summary_response += (
            f"• 已完成班次/Total Completed shifts: {total_completed_shifts}\n"
        )
        summary_response += f"• 待簽退/Waiting for check out: {total_pending_shifts}\n"
        summary_response += f"• 已簽到/Already checked in: {workers_checked_in}\n"
        summary_response += f"• 已簽退/Already checked out: {workers_checked_out}\n"

        final_response = summary_response + detailed_response
        return final_response

    except Exception as e:
        logging.error(f"Error reading today's attendance situation: {str(e)}")
        return f"❌ Error reading today's attendance situation: {str(e)}"


# chatbot function
async def read_today_attendance_situation_by_chatbot(sender: str, date_obj=None):
    try:
        if date_obj is None:
            today = get_this_day()
            date_obj = today
            logging.info(f"No date provided, using today's date: {today}")

        sender_info = await validate_mobile_from_whatsapp(sender)
        sender_name = (sender_info.english_name
                       if sender_info.english_name
                       else sender_info.payee_name
                       )

        if isinstance(date_obj, str):
            try:
                date_obj = datetime.strptime(date_obj, "%Y-%m-%d").date()
                logging.info(f"Converted string date to date object: {date_obj}")
            except ValueError:
                logging.error(
                    f"Invalid date format: {date_obj}. U∂çsing today's date instead."
                )
                date_obj = get_this_day()

        all_projects = await Project.find(Project.deleted_at == None).to_list()
        all_projects.sort(key=lambda p: p.project_code)

        total_attendance_count = 0
        project_attendance_data = []

        for project in all_projects: 
            attendance = await AttendanceRecord.get_today_attendance_for_project(str(project.id), 
                                                                                 date_obj)
            if attendance:
                total_attendance_count += len(attendance)
            project_attendance_data.append((project, attendance))

        response = f"Hi {sender_name}! 今日/Today({date_obj.strftime('%Y-%m-%d')} {date_obj.strftime('%A')})嘅出勤情況如下/attendance status is below:\n"
        response += f"總項目數/All project count: {len(all_projects)}\n"
        response += f"總出勤人數/All attendance count: {total_attendance_count}\n"

        for project, _ in project_attendance_data:
            project_attendance_info = await read_today_attendance_stituations_function(
                str(project.id), date_obj
            )
            response += "--------------------------------\n"
            response += project_attendance_info
            response += "\n"

        return response
    except Exception as e:
        import traceback

        logging.error(f"Error reading today's attendance situation: {str(e)}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return f"Error reading today's attendance situation: {str(e)}"
