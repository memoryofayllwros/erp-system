import calendar
import datetime
import logging
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from src.models.user_model import WorkType
from infrastructure.database.database_connection import get_grid_fs
from src.utils.hk_holidays import is_holiday_with_sunday
from assets.fonts.font_utils import register_fonts

from src.utils.datetime_standarization_helpers import get_this_moment

def calculate_text_height(text, font_size=7.5, line_height_factor=1.1):

    if not text:
        return 0.6

    lines = text.count("<br/>") + 1

    line_height = font_size * line_height_factor / 28.35  # Convert points to cm
    total_height = lines * line_height

    padding = 0.15 if lines > 1 else 0.1
    return max(0.6, total_height + padding)


def format_shift_time(shift, total_rounds=1):
    if not shift:
        return ""

    check_in = shift.get("check_in_time", "")
    check_out = shift.get("check_out_time", "")
    is_late_check_in = shift.get("is_late_check_in", False)
    is_early_check_out = shift.get("is_early_check_out", False)
    check_in_method = shift.get("check_in_method", "")
    check_out_method = shift.get("check_out_method", "")

    if not check_in and not check_out:
        return ""

    def add_image_indicator(time_str, method):
        if method == "image":
            return f"<u>{time_str}</u>"
        return time_str

    if check_in and check_out:
        if is_late_check_in and is_early_check_out:
            time_string = f'<font color="red">{add_image_indicator(check_in, check_in_method)}</font><br/><font color="red">{add_image_indicator(check_out, check_out_method)}</font>'
        elif is_late_check_in:
            time_string = f'<font color="red">{add_image_indicator(check_in, check_in_method)}</font><br/>{add_image_indicator(check_out, check_out_method)}'
        elif is_early_check_out:
            time_string = f'{add_image_indicator(check_in, check_in_method)}<br/><font color="red">{add_image_indicator(check_out, check_out_method)}</font>'
        else:
            time_string = f"{add_image_indicator(check_in, check_in_method)}<br/>{add_image_indicator(check_out, check_out_method)}"
    elif check_in:
        if is_late_check_in:
            time_string = f'<font color="red">{add_image_indicator(check_in, check_in_method)}</font><br/>-'
        else:
            time_string = f"{add_image_indicator(check_in, check_in_method)}<br/>-"
    elif check_out:
        if is_early_check_out:
            time_string = f'-<br/><font color="red">{add_image_indicator(check_out, check_out_method)}</font>'
        else:
            time_string = f"-<br/>{add_image_indicator(check_out, check_out_method)}"
    else:
        return ""

    prefix_parts = []
    if prefix_parts:
        prefix = ":".join(prefix_parts) + "<br/>"
        time_string = f"{prefix}{time_string}"

    return time_string


async def create_attendance_pdf(project_title, project_code, all_months_data):

    register_fonts()

    filename = f"temp_attendance_{project_code}_{get_this_moment().strftime('%Y%m%d_%H%M')}.pdf"
    
    # Track whether LOT and IMG appear in remarks
    has_lot = False
    has_img = False

    def add_page_number(canvas, doc):
        canvas.saveState()
        page_num = canvas.getPageNumber()
        page_width, page_height = landscape(A4)

        # Table boundaries
        # Page has 0.5cm margins, table is 28cm wide
        # Table starts at 0.5cm and ends at 28.5cm from left edge
        table_left = 0.5 * cm
        table_right = 28.5 * cm

        # Draw page number aligned with right edge of table
        canvas.setFont("aptos", 10)
        page_text = f"Page {page_num} of {total_pages}"
        page_text_width = canvas.stringWidth(page_text, "aptos", 10)
        x_position = table_right - page_text_width
        y_position = 0.7 * cm
        canvas.drawString(x_position, y_position, page_text)
        
        # Draw footnotes only if they appear in remarks
        canvas.setFont("aptos", 8)
        current_y = 0.5 * cm
        
        if has_lot:
            footnote_lot = "* LOT: Lunch Overtime"
            canvas.drawString(table_left, current_y, footnote_lot)
            current_y += 0.7 * cm
        
        if has_img:
            footnote_img = "* IMG: Image-based Special Attendance, underlined text indicates this attendance is Image-based Special Attendance"
            canvas.drawString(table_left, current_y, footnote_img)
        
        canvas.restoreState()
        logging.info(f"Total pages: {total_pages}")


    doc = SimpleDocTemplate(
        filename,
        pagesize=landscape(A4),
        rightMargin=0.5 * cm,
        leftMargin=0.5 * cm,
        topMargin=1 * cm,
        bottomMargin=1.3 * cm,
    )

    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title_style",
        parent=styles["Heading1"],
        fontName="aptos-bold",
        fontSize=14,
        alignment=0,
        spaceAfter=2,
    )

    subtitle_style = ParagraphStyle(
        "subtitle_style",
        parent=styles["Normal"],
        fontName="songti-sc-regular",
        fontSize=10,
        spaceAfter=5,
        alignment=0,  # 1 = TA_CENTER for vertical centering
    )
    table_text_style = ParagraphStyle(
        "table_text_style",
        parent=styles["Normal"],
        fontName="aptos",
        fontSize=8,
        alignment=1,
    )

    table_label_style = ParagraphStyle(
        "table_label_style",
        parent=styles["Normal"],
        fontName="aptos-bold",
        fontSize=8,
        alignment=1,
    )

    table_time_style = ParagraphStyle(
        "table_time_style",
        parent=styles["Normal"],
        fontName="aptos",
        fontSize=6,
        alignment=1,
        spaceBefore=0,
        spaceAfter=0,
        leading=5.5,
    )

    end_marker_style = ParagraphStyle(
        "end_marker_style",
        parent=styles["Normal"],
        fontName="aptos",
        fontSize=8,
        alignment=1,
        wordWrap="CJK",
    )

    for month_data in all_months_data:
        year = month_data["year"]
        month = month_data["month"]
        work_type_groups = month_data["work_type_groups"]

        month_days = calendar.monthrange(year, month)[1]

        total_width = 28 * cm
        no_col_width = 0.6 * cm
        staff_no_col_width = 1.4 * cm
        name_col_width = 2.5 * cm
        day_month_col_width = 1.2 * cm
        working_days_col_width = 1.2 * cm
        remarks_col_width = 1.5 * cm
        day_col_width = (
            total_width - no_col_width - staff_no_col_width - name_col_width - 
            day_month_col_width - working_days_col_width - remarks_col_width
        ) / month_days
        col_widths = (
            [no_col_width, staff_no_col_width, name_col_width, day_month_col_width]
            + [day_col_width] * month_days
            + [working_days_col_width, remarks_col_width]
        )

        for work_type_group in work_type_groups:
            work_type = work_type_group["work_type"]
            
            if isinstance(work_type, str):
                work_type_mapping = {
                    "Office Full Time": WorkType.office_ft,
                    "Office Part Time": WorkType.office_pt,
                    "Warehouse": WorkType.wh,
                    "Site": WorkType.site,
                    "office_ft": WorkType.office_ft,
                    "office_pt": WorkType.office_pt,
                    "wh": WorkType.wh,
                    "site": WorkType.site,
                }
                work_type_enum = work_type_mapping.get(work_type, WorkType.office_ft)
            else:
                work_type_enum = WorkType(work_type)
            
            day_headers = []
            for d in range(1, month_days + 1):
                off_work_day = is_holiday_with_sunday(year, month, d, work_type_enum)
                logging.info(f"Off work day: {off_work_day} for {work_type_enum} on {datetime.date(year, month, d)}")

                if off_work_day:
                    header_text = f'<font color="red">{d}</font>'
                else:
                    header_text = f"{d}"

                day_headers.append(header_text)

            work_type_display = work_type_enum.value
            
            elements.append(Paragraph(f"<u>{work_type_display} Attendance Record</u>", title_style)) # 員工出勤記錄表
            elements.append(Spacer(1, 2.0))
            elements.append(Paragraph(f"Project Name: <u>{project_code} - {project_title}</u> | Date: <u>{datetime.date(year, month, 1).strftime('%Y-%m-%d')} - {datetime.date(year, month, month_days).strftime('%Y-%m-%d')}</u>", subtitle_style))
            elements.append(Spacer(1, 2.0))

            workers = work_type_group["workers"]
            
            work_type_style = ParagraphStyle(
                "work_type_style",
                parent=styles["Heading2"],
                fontName="aptos-bold",
                fontSize=12,
                alignment=0,
                spaceBefore=1,
                spaceAfter=0.5)

            worker_info_table_headers = [
                "No.",
                f"{work_type_display} No.",
                "Employee's Name",
                "Day/<br/>Month",
                *day_headers,
                "Working Days",
                "Remarks",
            ]

            data = [[Paragraph(h, table_text_style) for h in worker_info_table_headers]]

            workers_with_attendance = [w for w in workers if w.get("start_end_times")]

            worker_row_heights = []

            for w, index in zip(workers_with_attendance, range(1, len(workers_with_attendance) + 1)):
                worker_name_html = w["payee_name"]
                name_height = calculate_text_height(
                    worker_name_html, font_size=8, line_height_factor=1.3
                )

                day_month_text = "IN<br/>OUT"
                day_month_height = calculate_text_height(
                    day_month_text, font_size=8, line_height_factor=1.3
                )

                max_attendance_height = 0.8

                row = [
                    Paragraph(str(index), table_text_style),
                    Paragraph(w["worker_no"], table_text_style),
                    Paragraph(worker_name_html, table_text_style),
                    Paragraph(day_month_text, table_text_style),
                ]

                for d in range(1, month_days + 1):
                    if d in w.get("start_end_times", {}):
                        day_data = w["start_end_times"][d]
                        shifts = day_data.get("shifts", [])

                        if shifts:
                            time_html_parts = []
                            total_rounds = len(shifts)

                            for i, shift in enumerate(shifts):
                                time_string = format_shift_time(
                                    shift, total_rounds=total_rounds
                                )
                                if time_string:
                                    time_html_parts.append(time_string)

                            if time_html_parts:
                                if len(time_html_parts) > 1:
                                    time_html = "<br/><br/>".join(time_html_parts)
                                else:
                                    time_html = time_html_parts[0]

                                day_height = calculate_text_height(
                                    time_html, font_size=6, line_height_factor=1.2
                                )
                                max_attendance_height = max(
                                    max_attendance_height, day_height
                                )

                                cell_height = max(0.8, day_height + 0.1)

                                nested_data = [[Paragraph(time_html, table_time_style)]]

                                cell = Table(
                                    nested_data,
                                    rowHeights=[cell_height * cm],
                                    colWidths=[day_col_width],
                                )
                                cell.canSplit = True
                                cell.splitByRow = 1

                                cell.setStyle(
                                    TableStyle(
                                        [
                                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                            ("FONTSIZE", (0, 0), (-1, -1), 6),
                                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                            ("GRID", (0, 0), (-1, -1), 0, colors.white),
                                        ]
                                    )
                                )

                                row.append(cell)
                            else:
                                row.append("")
                        else:
                            row.append("")
                    else:
                        row.append("")

                total_days_worked = len([d for d in range(1, month_days + 1) 
                                       if d in w.get("start_end_times", {}) and w["start_end_times"][d].get("shifts")])
                
                working_days = w["total_working_days"]
                if isinstance(working_days, (int, float)):
                    if working_days == int(working_days):
                        working_days_text = str(int(working_days))
                    else:
                        working_days_text = f"{working_days:.1f}"
                else:
                    working_days_text = str(working_days)
                
                # Generate remarks text based on image-based attendance dates and lunch overtime
                remarks_parts = []
                if w.get("image_attendance_dates"):
                    has_img = True
                    for date in w["image_attendance_dates"]:
                        # Format date with asterisk footnote for image attendance
                        remarks_parts.append(f"IMG {date.strftime('%m-%d')}")
                if w.get("lunch_overtime_dates"):
                    has_lot = True
                    for date in w["lunch_overtime_dates"]:
                        # Format date with dagger footnote for lunch overtime
                        remarks_parts.append(f"LOT {date.strftime('%m-%d')}")
                remarks_text = "<br/>".join(remarks_parts)
                
                days_height = calculate_text_height(
                    str(total_days_worked), font_size=8, line_height_factor=1.3
                )
                working_days_height = calculate_text_height(
                    working_days_text, font_size=8, line_height_factor=1.3
                )
                remarks_height = calculate_text_height(
                    remarks_text, font_size=8, line_height_factor=1.3
                )

                worker_row_height = max(
                    name_height, day_month_height, max_attendance_height, 
                    days_height, working_days_height, remarks_height
                )
                worker_row_height = max(
                    0.8, worker_row_height + 0.2
                )
                worker_row_heights.append(worker_row_height * cm)

                row.append(Paragraph(working_days_text, table_text_style))
                row.append(Paragraph(remarks_text, table_time_style))
                data.append(row)

            daily_worker_counts = []
            daily_manual_input_counts = []
            for d in range(1, month_days + 1):
                workers_present_today = 0
                manual_input_present_today = 0
                for w in workers_with_attendance:
                    if d in w.get("start_end_times", {}):
                        day_data = w["start_end_times"][d]
                        shifts = day_data.get("shifts", [])
                        if shifts:
                            workers_present_today += 1
                            # Check if any shift used manual input (image-based attendance)
                            for shift in shifts:
                                check_in_method = shift.get("check_in_method", "")
                                check_out_method = shift.get("check_out_method", "")
                                if check_in_method == "image" or check_out_method == "image":
                                    manual_input_present_today += 1
                                    break  # Count this worker only once per day
                daily_worker_counts.append(workers_present_today)
                daily_manual_input_counts.append(manual_input_present_today)

            daily_count_row = [
                Paragraph("Total:", table_text_style),
                "",
                "",
                "",
            ]

            for count in daily_worker_counts:
                if count > 0:
                    daily_count_row.append(Paragraph(str(count), table_text_style))
                else:
                    daily_count_row.append("")

            daily_count_row.append(Paragraph("", table_text_style))
            daily_count_row.append(Paragraph("", table_text_style))
            data.append(daily_count_row)

            manual_input_count_row = [
                Paragraph("Manual Input:", table_text_style),
                "",
                "",
                "",
            ]

            for count in daily_manual_input_counts:
                if count > 0:
                    manual_input_count_row.append(Paragraph(str(count), table_text_style))
                else:
                    manual_input_count_row.append("")

            manual_input_count_row.append(Paragraph("", table_text_style))
            manual_input_count_row.append(Paragraph("", table_text_style))
            data.append(manual_input_count_row)

            worker_info_table = Table(
                data,
                colWidths=col_widths,
                repeatRows=1,
                splitByRow=1
                )

            # Calculate row indices
            total_workers_row_index = len(data) - 2  # Total row is second to last
            manual_input_row_index = len(data) - 1   # Manual input row is last

            worker_info_table.setStyle(
                TableStyle(
                    [
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
                        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.white]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),

                        # Add big padding for the daily_count_row (Total row) - 0.8cm
                        ("LEFTPADDING", (0, total_workers_row_index), (-1, total_workers_row_index), 0),
                        ("RIGHTPADDING", (0, total_workers_row_index), (-1, total_workers_row_index), 0),
                        ("TOPPADDING", (0, total_workers_row_index), (-1, total_workers_row_index), 10),
                        ("BOTTOMPADDING", (0, total_workers_row_index), (-1, total_workers_row_index), 10),
                        ("SPAN", (0, total_workers_row_index), (3, total_workers_row_index)), # Total row spans first 4 cells

                        # Add big padding for the manual_input_row_index (Manual input row) - 0.8cm
                        ("LEFTPADDING", (0, manual_input_row_index), (-1, manual_input_row_index), 0),
                        ("RIGHTPADDING", (0, manual_input_row_index), (-1, manual_input_row_index), 0),
                        ("TOPPADDING", (0, manual_input_row_index), (-1, manual_input_row_index), 10),
                        ("BOTTOMPADDING", (0, manual_input_row_index), (-1, manual_input_row_index), 10),
                        ("SPAN", (0, manual_input_row_index), (3, manual_input_row_index)), # Manual input row spans first 4 cells
                    ]
                )
            )

            elements.append(worker_info_table)
            elements.append(Spacer(1, 0.3))
            elements.append(Paragraph(f"***{work_type_display} Attendance Record End***", end_marker_style))
            elements.append(Spacer(1, 1.0))
            if work_type_group != work_type_groups[-1]:
                elements.append(Spacer(1, 0.5))

        if month_data != all_months_data[-1]:
            elements.append(PageBreak())

    def dummy_page_callback(canvas, doc):
        pass

    temp_filename = f"temp_{filename}"

    temp_doc = SimpleDocTemplate(
        temp_filename,
        pagesize=landscape(A4),
        rightMargin=0.5 * cm,
        leftMargin=0.5 * cm,
        topMargin=0.7 * cm,
        bottomMargin=0.7 * cm,
    )
    temp_story = elements[:]
    temp_doc.build(
        temp_story, onFirstPage=dummy_page_callback, onLaterPages=dummy_page_callback
    )
    total_pages = temp_doc.page

    logging.info(f"Total pages: {total_pages}")

    try:
        os.remove(temp_filename)
    except:
        pass

    #worker_info_table._argH = worker_row_heights  # enforce calculated row heights
    #worker_info_table.splitByRow = 1
    #worker_info_table.canSplit = True

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)

    return filename


async def generate_attendance_record_pdf(project_id: str) -> dict:
    from bson import ObjectId

    from src.models.attendance_record_model import AttendanceRecord
    from src.models.project_model import Project

    try:
        project_info = await Project.find_one(
            Project.id == ObjectId(project_id), Project.deleted_at == None
        )
        if not project_info:
            raise ValueError(f"Project with ID {project_id} not found")

        project_code = project_info.project_code
        project_title = project_info.project_title

        all_records = await AttendanceRecord.find(
            AttendanceRecord.project_id == project_id,
            AttendanceRecord.deleted_at == None,
        ).to_list()

        if not all_records:
            logging.warning(
                f"No attendance records found for project {project_id}, returning None"
            )
            return None

        attendance_dates = [
            record.attendance_date for record in all_records if record.attendance_date
        ]
        if not attendance_dates:
            logging.warning(
                f"No valid attendance dates found for project {project_id}, returning None"
            )
            return None

        earliest_date = min(attendance_dates)
        latest_date = max(attendance_dates)

        all_months_data = []
        for year in range(earliest_date.year, latest_date.year + 1):
            for month in range(1, 13):
                if year == earliest_date.year and month < earliest_date.month:
                    continue
                if year == latest_date.year and month > latest_date.month:
                    continue

                work_type_groups = (
                    await AttendanceRecord.get_attendance_records_for_table_display(
                        project_id=project_id, year=year, month=month
                    )
                )
                if work_type_groups:
                    all_months_data.append(
                        {"year": year, "month": month, "work_type_groups": work_type_groups}
                    )

        if not all_months_data:
            logging.warning(
                f"No attendance data found for any month in project {project_id}"
            )
            return None

        final_filename = f"attendance_report_{project_code}_{earliest_date.strftime('%Y%m')}_{latest_date.strftime('%Y%m')}.pdf"

        pdf_file_path = await create_attendance_pdf(
            project_title=project_title,
            project_code=project_code,
            all_months_data=all_months_data,
        )

        with open(pdf_file_path, "rb") as pdf_file:
            pdf_content = pdf_file.read()

        grid_fs = await get_grid_fs()

        metadata = {
            "project_id": project_id,
            "project_title": project_title,
            "project_code": project_code,
            "earliest_date": earliest_date.isoformat() if earliest_date else None,
            "latest_date": latest_date.isoformat() if latest_date else None,
        }
        file_id = await grid_fs.upload_from_stream(
            final_filename, pdf_content, metadata=metadata
        )

        update_result = await Project.update_attendance_record_id(
            project_id=project_id,
            attendance_record_id=str(file_id)
        )
        if update_result.get("status") == "success":
            logging.info(f"✅ Successfully updated attendance_record_id for project {project_id}: {file_id}")
        else:
            logging.error(f"❌ Failed to update attendance_record_id: {update_result.get('message', 'Unknown error')}")
            return None

        try:
            os.remove(pdf_file_path)
            logging.info(f"Temporary PDF file removed")
        except Exception as e:
            logging.warning(f"Could not remove temporary PDF: {str(e)}")

        return str(file_id)

    except Exception as e:
        logging.error(f"Error generating attendance record PDF: {str(e)}")
        raise e
