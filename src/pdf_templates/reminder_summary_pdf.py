import logging
import os
import tempfile
import warnings
from datetime import datetime
from typing import Any, Dict, List

from fpdf import FPDF

from src.utils.datetime_standarization_helpers import get_this_day
from src.utils.datetime_standarization_helpers import HK_TZ 
    # Filter out specific font warnings
warnings.filterwarnings(
    "ignore", category=UserWarning, message="cmap value too big/small:.*"
)

logger = logging.getLogger(__name__)


class ReminderSummaryPDF(FPDF):
    def __init__(self, project_info: dict, reminders: List[Dict[str, Any]]):
        try:
            super().__init__(orientation="P", format="A4")

            # Get the absolute path to the fonts directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            fonts_dir = os.path.join(current_dir, "..", "utils", "fonts")
            self.assets_dir = os.path.join(current_dir, "..", "Assets", "Image")

            # Add Chinese fonts
            font_path_regular = os.path.join(fonts_dir, "notosans-hk-regular.ttf")
            font_path_bold = os.path.join(fonts_dir, "notosans-hk-bold.ttf")

            if not os.path.exists(font_path_regular):
                raise FileNotFoundError(
                    f"Regular font file not found at {font_path_regular}"
                )
            if not os.path.exists(font_path_bold):
                raise FileNotFoundError(f"Bold font file not found at {font_path_bold}")

            # Add Chinese fonts with UTF-8 encoding
            self.add_font("notosans-hk-regular", "", font_path_regular, uni=True)
            self.add_font("notosans-hk-bold", "", font_path_bold, uni=True)

            # Set default font
            self.set_font("notosans-hk-regular", "", 11)

            self.set_margins(25, 25, 25)
            self.set_auto_page_break(auto=True, margin=40)
            self.project_info = project_info
            self.reminders = reminders

        except Exception as e:
            logger.error(f"Error initializing ReminderSummaryPDF: {str(e)}")
            raise

    def header(self):
        """Automatically adds a header to each page."""
        try:
            # Add logo on top right
            logo_path = os.path.join(self.assets_dir, "gcb-letter head.png")
            if os.path.exists(logo_path):
                self.image(logo_path, x=170, y=10, w=25)

            # Set font for header
            self.set_font("notosans-hk-bold", "", 16)
            self.set_xy(25, 45)

            # Title
            self.cell(0, 10, "Project Reminder List", ln=True, align="C")
            self.ln(5)

            # Project information - only on first page
            if self.page_no() == 1:
                self.set_font("notosans-hk-regular", "", 12)
                self.cell(
                    0,
                    6,
                    f"Project No: {self.project_info.get('project_code', 'N/A')}",
                    ln=True,
                )

                if self.project_info.get("project_title"):
                    self.cell(
                        0,
                        6,
                        f"Project Title: {self.project_info['project_title']}",
                        ln=True,
                    )

                # Project location
                location_parts = []
                if self.project_info.get("project_location"):
                    loc = self.project_info["project_location"]
                    if isinstance(loc, dict):
                        if loc.get("district"):
                            location_parts.append(loc["district"])
                        if loc.get("street"):
                            location_parts.append(loc["street"])
                        if loc.get("building"):
                            location_parts.append(loc["building"])
                    elif isinstance(loc, str):
                        location_parts.append(loc)

                if location_parts:
                    location_str = ", ".join(location_parts)
                    self.cell(0, 6, f"Project Location: {location_str}", ln=True)

                # Generation date
                current_date = get_this_day().strftime("%Y-%m-%d %H:%M")
                self.cell(0, 6, f"Generated: {current_date}", ln=True)

                self.ln(10)
            else:
                # Continuation page - just project number and page indicator
                self.set_font("notosans-hk-regular", "", 12)
                self.cell(
                    0,
                    6,
                    f"Project No: {self.project_info.get('project_code', 'N/A')} (Continued)",
                    ln=True,
                )
                self.ln(5)

                # Add table headers on continuation pages
                self.add_table_header()

        except Exception as e:
            logger.error(f"Error in header: {str(e)}")
            raise

    def add_table_header(self):
        """Add table headers (used for continuation pages)"""
        try:
            # Table header
            self.set_font("notosans-hk-bold", "", 10)
            self.set_fill_color(200, 200, 200)

            # Column widths - updated for combined datetime column
            col_widths = [15, 45, 70, 30, 20]

            # Table headers
            headers = ["#", "Datetime", "Description", "Receiver", "Status"]

            # Draw header row
            for i, header in enumerate(headers):
                self.cell(col_widths[i], 15, header, 1, 0, "C", True)
            self.ln()

            # Reset font for content
            self.set_font("notosans-hk-regular", "", 9)
            self.set_fill_color(255, 255, 255)

        except Exception as e:
            logger.error(f"Error adding table header: {str(e)}")
            raise

    def footer(self):
        """Add footer with page number."""
        try:
            self.set_y(-15)
            self.set_font("notosans-hk-regular", "", 8)
            self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")
        except Exception as e:
            logger.error(f"Error in footer: {str(e)}")
            raise

    def add_reminder_table(self):
        """Add the reminder table to the PDF."""
        try:
            # Add table header for first page
            self.add_table_header()

            # Sort reminders by datetime
            def sort_key(reminder):
                reminder_datetime = reminder.get("reminder_datetime", "")

                try:
                    dt_obj = None
                    if isinstance(reminder_datetime, str):
                        # Try parsing the datetime string
                        try:
                            dt_obj = datetime.strptime(
                                reminder_datetime, "%Y-%m-%d %H:%M:%S"
                            )
                        except ValueError:
                            try:
                                dt_obj = datetime.strptime(
                                    reminder_datetime, "%Y-%m-%d %H:%M"
                                )
                            except ValueError:
                                try:
                                    dt_obj = datetime.strptime(
                                        reminder_datetime, "%Y-%m-%dT%H:%M:%S"
                                    )
                                except ValueError:
                                    try:
                                        dt_obj = datetime.strptime(
                                            reminder_datetime, "%Y-%m-%dT%H:%M:%S.%f"
                                        )
                                    except ValueError:
                                        return HK_TZ.localize(
                                            datetime.min.replace(year=1900)
                                        )
                    elif hasattr(reminder_datetime, "strftime"):
                        # It's already a datetime object
                        dt_obj = reminder_datetime

                    if dt_obj:
                        if dt_obj.tzinfo is None:
                            dt_obj = HK_TZ.localize(dt_obj)
                        hk_dt = dt_obj.astimezone(HK_TZ)
                        return hk_dt
                    else:
                        return HK_TZ.localize(datetime.min.replace(year=1900))
                except Exception:
                    return HK_TZ.localize(datetime.min.replace(year=1900))

            sorted_reminders = sorted(self.reminders, key=sort_key)

            # Column widths - same as in add_table_header
            col_widths = [15, 45, 70, 30, 20]

            for idx, reminder in enumerate(sorted_reminders, 1):
                # Get reminder data first
                description = reminder.get("reminder_description", "")

                # Calculate row height based on description length
                desc_lines = max(
                    1, (len(description) // 50) + 1
                )  # More accurate calculation
                row_height = max(
                    12, desc_lines * 5
                )  # Minimum height with proper spacing

                # Check if we need a new page BEFORE starting the row
                # Account for footer space and minimum space for one more row
                if self.get_y() + row_height > 250:  # Leave space for footer
                    self.add_page()
                    # Table header is automatically added by the header() method for continuation pages

                reminder_datetime = reminder.get("reminder_datetime", "")
                formatted_datetime = ""

                if reminder_datetime:
                    try:
                        dt_obj = None
                        # Handle different datetime formats
                        if isinstance(reminder_datetime, str):
                            # Try parsing different datetime string formats
                            try:
                                dt_obj = datetime.strptime(
                                    reminder_datetime, "%Y-%m-%d %H:%M:%S"
                                )
                            except ValueError:
                                try:
                                    dt_obj = datetime.strptime(
                                        reminder_datetime, "%Y-%m-%d %H:%M"
                                    )
                                except ValueError:
                                    try:
                                        dt_obj = datetime.strptime(
                                            reminder_datetime, "%Y-%m-%dT%H:%M:%S"
                                        )
                                    except ValueError:
                                        try:
                                            dt_obj = datetime.strptime(
                                                reminder_datetime,
                                                "%Y-%m-%dT%H:%M:%S.%f",
                                            )
                                        except ValueError:
                                            # If all parsing fails, use as string
                                            formatted_datetime = str(reminder_datetime)
                        elif hasattr(reminder_datetime, "strftime"):
                            # It's already a datetime object
                            dt_obj = reminder_datetime

                        if dt_obj:
                            if dt_obj.tzinfo is None:
                                dt_obj = HK_TZ.localize(dt_obj)

                            # Convert to Hong Kong timezone
                            hk_dt = dt_obj.astimezone(HK_TZ)

                            # Format as combined datetime string
                            formatted_datetime = hk_dt.strftime("%m/%d/%Y %I:%M %p")

                    except Exception as e:
                        # Fallback to string representation
                        formatted_datetime = str(reminder_datetime)
                        logger.warning(
                            f"Could not parse reminder_datetime: {reminder_datetime}, error: {e}"
                        )
                else:
                    # Fallback: check for separate date/time fields (legacy support)
                    reminder_date = reminder.get("reminder_date", "")
                    reminder_time = reminder.get("reminder_time", "")

                    if reminder_date and reminder_time:
                        try:
                            # Combine date and time strings
                            datetime_str = f"{reminder_date} {reminder_time}"
                            dt_obj = datetime.strptime(
                                datetime_str, "%Y-%m-%d %H:%M:%S"
                            )

                            if dt_obj.tzinfo is None:
                                dt_obj = HK_TZ.localize(dt_obj)
                            hk_dt = dt_obj.astimezone(HK_TZ)
                            formatted_datetime = hk_dt.strftime("%m/%d/%Y %I:%M %p")
                        except Exception as e:
                            # Fallback to combining strings as-is
                            if reminder_date and reminder_time:
                                formatted_datetime = f"{reminder_date} {reminder_time}"
                            elif reminder_date:
                                formatted_datetime = str(reminder_date)
                            else:
                                formatted_datetime = ""
                    elif reminder_date:
                        formatted_datetime = str(reminder_date)

                description = reminder.get("reminder_description", "")
                # Get contact name
                contact_name = reminder.get("name", "")

                # Determine status
                status = "Sent" if reminder.get("sent", False) else "Pending"

                # Store starting position
                y_start = self.get_y()
                x_start = self.get_x()

                # Draw all cells for this row

                # Column 1: Serial Number
                self.set_xy(x_start, y_start)
                self.cell(col_widths[0], row_height, str(idx), 1, 0, "C")

                # Column 2: Combined Datetime (was Date + Time)
                self.set_xy(x_start + col_widths[0], y_start)
                self.cell(col_widths[1], row_height, formatted_datetime, 1, 0, "C")

                # Column 3: Description (multiline)
                desc_x = x_start + col_widths[0] + col_widths[1]
                desc_y = y_start

                # Draw the border for description cell first
                self.rect(desc_x, desc_y, col_widths[2], row_height)

                # Set position inside the cell with padding
                self.set_xy(desc_x + 2, desc_y + 2)

                # Use multi_cell for description with proper width
                self.multi_cell(col_widths[2] - 4, 4, description, 0, "L")

                # Column 4: Receiver
                receiver_x = x_start + col_widths[0] + col_widths[1] + col_widths[2]
                self.set_xy(receiver_x, y_start)
                self.cell(col_widths[3], row_height, contact_name, 1, 0, "C")

                # Column 5: Status
                status_x = receiver_x + col_widths[3]
                self.set_xy(status_x, y_start)
                self.cell(col_widths[4], row_height, status, 1, 0, "C")

                # Move to next row
                self.set_xy(x_start, y_start + row_height)

            # Summary section
            self.ln(10)
            self.set_font("notosans-hk-bold", "", 12)
            self.cell(0, 8, "Summary", ln=True)
            self.set_font("notosans-hk-regular", "", 10)

            total_reminders = len(self.reminders)
            sent_reminders = len([r for r in self.reminders if r.get("sent", False)])
            pending_reminders = total_reminders - sent_reminders

            self.cell(0, 6, f"Total Reminders: {total_reminders}", ln=True)
            self.cell(0, 6, f"Sent: {sent_reminders}", ln=True)
            self.cell(0, 6, f"Pending: {pending_reminders}", ln=True)

        except Exception as e:
            logger.error(f"Error adding reminder table: {str(e)}")
            raise

    def generate_reminder_summary_pdf(self):
        """Generate the complete PDF."""
        try:
            self.add_page()
            self.add_reminder_table()

            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_path = temp_file.name
            temp_file.close()

            # Output PDF to temporary file
            self.output(temp_path)

            # Read the PDF content
            with open(temp_path, "rb") as f:
                pdf_content = f.read()

            # Clean up temporary file
            os.unlink(temp_path)

            return pdf_content

        except Exception as e:
            logger.error(f"Error generating PDF: {str(e)}")
            raise


async def generate_reminder_summary_pdf(
    project_info: dict, reminders: List[Dict[str, Any]]
) -> bytes:
    try:
        logger.info(
            f"Generating reminder summary PDF for project {project_info.get('project_code', 'Unknown')}"
        )

        pdf_generator = ReminderSummaryPDF(project_info, reminders)
        pdf_content = pdf_generator.generate_reminder_summary_pdf()

        logger.info(
            f"Successfully generated reminder summary PDF ({len(pdf_content)} bytes)"
        )

        return pdf_content

    except Exception as e:
        logger.error(f"Error generating reminder summary PDF: {str(e)}")
        raise
