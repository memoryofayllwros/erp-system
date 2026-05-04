import logging
from datetime import date, datetime
from typing import List, Optional

from beanie import Document
from pydantic import BaseModel, Field, computed_field

from src.utils.datetime_standarization_helpers import get_this_moment, get_this_day, HK_TZ

import os

from src.message_templates.message_response_templates import send_whatsapp_message_back
from src.models.attendance_record_model import AttendanceRecord


class SiteImage(BaseModel):
    # might require a more sophisticated way to calculate the match confidence, image comparison, etc.
    image_file_id: str
    image_timestamp: datetime
    lan: Optional[str] = None
    lon: Optional[str] = None  # collected from the image
    accuracy: Optional[str] = Field(default="0")  # GPS accuracy in meters
    is_accepted: bool = Field(default=False)


class GoogleMapsScreenshot(BaseModel):
    # might require image OCR to extract the buildings on the google maps screenshot, and then compare the buildings with the buildings surrounding the project location
    image_file_id: str
    screenshot_timestamp: datetime
    is_accepted: bool = Field(default=False)


class AttendanceViaImageModel(Document):
    user_id: str
    project_id: str
    user_waba: Optional[str] = None
    site_image: SiteImage
    google_maps_screenshot: GoogleMapsScreenshot

    attendance_time: datetime = Field(
        default_factory=get_this_moment
    )
    attendance_date: date = Field(
        default_factory=get_this_day
    )

    attendance_method: bool = Field(default=True)
    image_file_ids: Optional[List[str]] = Field(default=None)
    created_at: datetime = Field(default_factory=get_this_moment)
    deleted_at: Optional[datetime] = None

    class Settings:
        name = "attendance_via_image_collection"

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    async def upload_image_attendance_info_to_database(
        user_id: str,
        user_waba: str,
        project_id: str,
        site_image: SiteImage,
        google_maps_screenshot: GoogleMapsScreenshot,
    ):
        try:
            attendance_record = AttendanceViaImageModel(
                user_id=user_id,
                project_id=project_id,
                user_waba=user_waba,
                site_image=site_image,
                google_maps_screenshot=google_maps_screenshot,
            )

            await attendance_record.save()
            # Convert to main attendance system if both checks pass
            if site_image.is_accepted and google_maps_screenshot.is_accepted:
                await AttendanceViaImageModel.convert_to_main_attendance_system(
                    attendance_record
                )

            return attendance_record
        except Exception as e:
            raise

    @staticmethod
    async def convert_to_main_attendance_system(
        attendance_record: "AttendanceViaImageModel",
    ) -> bool:

        try:

            # Extract location data from site image with proper defaults
            latitude = (
                attendance_record.site_image.lan
                if attendance_record.site_image.lan
                else "0.0"
            )
            longitude = (
                attendance_record.site_image.lon
                if attendance_record.site_image.lon
                else "0.0"
            )
            accuracy = (
                attendance_record.site_image.accuracy
                if attendance_record.site_image.accuracy
                else "10.0"
            )

            actual_timestamp = attendance_record.site_image.image_timestamp

            # Collect all image file IDs from both site image and screenshot
            image_file_ids = []
            if attendance_record.site_image.image_file_id:
                image_file_ids.append(attendance_record.site_image.image_file_id)
            if attendance_record.google_maps_screenshot.image_file_id:
                image_file_ids.append(
                    attendance_record.google_maps_screenshot.image_file_id
                )

            # Use the main attendance system to process the check-in with image file IDs
            attendance_result = await AttendanceRecord.add_worker_attendance_record(
                project_id=attendance_record.project_id,
                user_id=attendance_record.user_id,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy,
                timestamp=actual_timestamp,
                attendance_method=False,  # False for Image-based attendance
                image_file_ids=image_file_ids if image_file_ids else None,
            )

            # Send WhatsApp message regardless of success or error
            try:
                ENABLE_WABA_NOTIFICATIONS = (
                    os.getenv("ENABLE_WABA_NOTIFICATIONS", "true").lower() == "true"
                )

                if ENABLE_WABA_NOTIFICATIONS and attendance_record.user_waba:
                    message = attendance_result.get("message", "").strip()
                    if message:
                        # Modify the message to indicate it's from image upload
                        image_message = message.replace("簽到", "透過照片簽到")

                        if attendance_result.get("status") == "success":
                            logging.info(
                                f"📱 Sending WhatsApp confirmation to {attendance_record.user_waba}"
                            )
                        else:
                            logging.info(
                                f"📱 Sending WhatsApp error message to {attendance_record.user_waba}"
                            )

                        await send_whatsapp_message_back(image_message, attendance_record.user_waba)
                        logging.info(
                            f"✅ WhatsApp message sent successfully to {attendance_record.user_waba}"
                        )
                    else:
                        logging.warning("No message returned from attendance system")
                else:
                    logging.warning(
                        "WhatsApp notifications disabled or WHATSAPP_NUMBER not configured"
                    )

            except Exception as whatsapp_error:
                logging.error(f"❌ Failed to send WhatsApp message: {whatsapp_error}")
                # Don't fail the conversion if WhatsApp fails

            if attendance_result.get("status") == "success":
                logging.info(
                    f"Successfully converted image attendance to main system for user "
                    f"{attendance_record.user_id}"
                )
                return True
            else:
                logging.error(
                    f"Failed to convert image attendance: {attendance_result.get('message', 'Unknown error')}"
                )
                return False

        except Exception as e:
            logging.error(
                f"Failed to convert image attendance to main attendance system: {str(e)}"
            )
            return False


    # 🔹 Attendance Processor
    @classmethod
    async def process_attendance_image(
        cls,
        user_id: str,
        user_waba: str,
        project_id: str,
        site_image_path: str,
        maps_screenshot_path: str,
        image_lat: Optional[float] = None,
        image_lon: Optional[float] = None
    ) -> Optional["AttendanceViaImageModel"]:

        try:
            # Step 1: Validate and process site image
            site_image_accepted = False
            try:
                # Create site image object with GPS data
                # Use Hong Kong timezone for consistent time handling
                current_hk_time = get_this_moment()
                site_image = SiteImage(
                    image_file_id=site_image_path,  # This should be the file ID, not path
                    image_timestamp=current_hk_time,
                    lan=str(image_lat) if image_lat is not None else None,
                    lon=str(image_lon) if image_lon is not None else None,
                    accuracy="10.0",
                    is_accepted=True  # Accept the site image by default
                )
                site_image_accepted = site_image.is_accepted

            except Exception as e:
                logging.error(f"Error processing site image: {str(e)}")
                return None

            # Step 2: Validate and process Google Maps screenshot
            maps_screenshot_accepted = False
            try:
                maps_screenshot = GoogleMapsScreenshot(
                    image_file_id=maps_screenshot_path,  # This should be the file ID, not path
                    screenshot_timestamp=current_hk_time,  # Use the same HK time
                    is_accepted=True,
                )

                maps_screenshot_accepted = maps_screenshot.is_accepted
            except Exception as e:
                logging.error(f"Error processing maps screenshot: {str(e)}")
                return None

            # Step 3: Create and save attendance record
            attendance = AttendanceViaImageModel(
                user_id=user_id,
                user_waba=user_waba,
                project_id=project_id,
                site_image=site_image,
                google_maps_screenshot=maps_screenshot,
            )
            await attendance.insert()

            # Step 4: Convert to main attendance system if both validations pass
            if site_image_accepted and maps_screenshot_accepted:
                await attendance.save()
                conversion_success = await cls.convert_to_main_attendance_system(
                    attendance
                )

                if conversion_success:
                    return attendance
                else:
                    return attendance
            else:
                return None

        except Exception as e:
            return None
