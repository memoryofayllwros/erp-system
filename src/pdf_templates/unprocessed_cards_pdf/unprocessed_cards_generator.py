import base64
import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from bson import ObjectId
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from src.models.user_model import User
from src.tools.work_permit_ocr_tool.work_permit_ocr import \
    process_worker_card_ocr
from infrastructure.database.database_connection import get_grid_fs
from assets.fonts.font_utils import register_fonts

logger = logging.getLogger(__name__)


class UnprocessedCardsPDFGenerator:
    """Comprehensive PDF generator for displaying all unprocessed cards for each user"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the PDF"""
        # Title style
        self.title_style = ParagraphStyle(
            "CustomTitle",
            parent=self.styles["Heading1"],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.black,
            fontName="notosans-hk-bold",
        )

        # Subtitle style
        self.subtitle_style = ParagraphStyle(
            "CustomSubtitle",
            parent=self.styles["Heading2"],
            fontSize=18,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=colors.black,
            fontName="notosans-hk-bold",
        )

        # User info style
        self.user_info_style = ParagraphStyle(
            "UserInfo",
            parent=self.styles["Normal"],
            fontSize=12,
            spaceAfter=15,
            alignment=TA_LEFT,
            fontName="notosans-hk-regular",
            leftIndent=20,
        )

        # Card count style
        self.card_count_style = ParagraphStyle(
            "CardCount",
            parent=self.styles["Normal"],
            fontSize=14,
            spaceAfter=10,
            alignment=TA_CENTER,
            textColor=colors.red,
            fontName="notosans-hk-bold",
        )

        # Summary style
        self.summary_style = ParagraphStyle(
            "Summary",
            parent=self.styles["Normal"],
            fontSize=11,
            spaceAfter=10,
            alignment=TA_LEFT,
            fontName="notosans-hk-regular",
        )

    async def generate_unprocessed_cards_pdf(self, output_path: str = None) -> bytes:
        try:
            logger.info("Starting unprocessed cards PDF generation")

            # Register fonts
            register_fonts()

            # Get all users with unprocessed cards
            users_with_cards = await self._get_users_with_unprocessed_cards()

            if not users_with_cards:
                logger.warning("No users found with unprocessed cards")
                return self._generate_empty_pdf()

            # Create PDF document
            if output_path:
                doc = SimpleDocTemplate(
                    output_path,
                    pagesize=A4,
                    rightMargin=20 * mm,
                    leftMargin=20 * mm,
                    topMargin=20 * mm,
                    bottomMargin=20 * mm,
                )
            else:
                # Create in memory
                buffer = BytesIO()
                doc = SimpleDocTemplate(
                    buffer,
                    pagesize=A4,
                    rightMargin=20 * mm,
                    leftMargin=20 * mm,
                    topMargin=20 * mm,
                    bottomMargin=20 * mm,
                )

            # Build PDF content
            story = []

            # Add title page
            story.extend(self._create_title_page(users_with_cards))
            story.append(PageBreak())

            # Add detailed pages for each user
            for user in users_with_cards:
                user_pages = await self._create_user_pages(user)
                story.extend(user_pages)

            doc.build(
                story,
                onFirstPage=self._add_page_number,
                onLaterPages=self._add_page_number,
            )

            if output_path:
                logger.info(f"PDF saved to: {output_path}")
                return None
            else:
                # Return bytes from memory buffer
                buffer.seek(0)
                pdf_bytes = buffer.getvalue()
                buffer.close()
                logger.info(f"PDF generated successfully with {len(pdf_bytes)} bytes")
                return pdf_bytes

        except Exception as e:
            logger.error(f"Error generating unprocessed cards PDF: {str(e)}")
            raise

    def _add_page_number(self, canvas: canvas.Canvas, doc):
        """Draw page number on each page (bottom-right corner)."""
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.setFont("notosans-hk-regular", 10)
        canvas.drawRightString(
            doc.pagesize[0] - 20 * mm,  # right margin
            15 * mm,  # distance from bottom
            text,
        )

    async def _get_users_with_unprocessed_cards(self) -> List[User]:
        """Fetch all active users regardless of card status"""
        try:
            # Find all active users
            all_users = await User.find(
                {"deleted_at": None}, {"is_active": True}
            ).to_list()

            # Sort users: first those with cards (by card count), then those without cards
            def card_count(user):
                unprocessed_count = len(user.cards_unprocessed or [])
                national_id_count = (
                    1
                    if hasattr(user, "national_id_card")
                    and user.national_id_card
                    and user.national_id_card.card_image_front
                    else 0
                )
                return unprocessed_count + national_id_count

            all_users.sort(key=card_count, reverse=True)

            # Count different user types for logging
            users_with_unprocessed = sum(
                1
                for u in all_users
                if u.cards_unprocessed and len(u.cards_unprocessed) > 0
            )
            users_with_national_id = sum(
                1
                for u in all_users
                if hasattr(u, "national_id_card")
                and u.national_id_card
                and u.national_id_card.card_image_front
            )
            users_with_no_cards = sum(
                1
                for u in all_users
                if (not u.cards_unprocessed or len(u.cards_unprocessed) == 0)
                and (
                    not hasattr(u, "national_id_card")
                    or not u.national_id_card
                    or not u.national_id_card.card_image_front
                )
            )

            logger.info(
                f"Found {len(all_users)} total users: {users_with_unprocessed} with unprocessed cards, "
                f"{users_with_national_id} with national ID, and {users_with_no_cards} with no cards"
            )

            return all_users

        except Exception as e:
            logger.error(f"Error fetching users: {str(e)}")
            raise

    def _create_title_page(self, users: List[User]) -> List:
        """Create the title page of the PDF"""
        story = []

        # Main title
        title = Paragraph("User Cards Report", self.title_style)
        story.append(title)
        story.append(Spacer(1, 30))

        # Subtitle
        subtitle = Paragraph(
            f"Generated on {get_this_moment().strftime('%B %d, %Y at %I:%M %p')}",
            self.subtitle_style,
        )
        story.append(subtitle)
        story.append(Spacer(1, 40))

        # Statistics
        total_users = len(users)
        total_unprocessed_cards = sum(len(u.cards_unprocessed or []) for u in users)
        total_national_id_cards = sum(
            1
            for u in users
            if hasattr(u, "national_id_card")
            and u.national_id_card
            and u.national_id_card.card_image_front
        )
        total_cards = total_unprocessed_cards + total_national_id_cards
        users_with_cards = sum(
            1
            for u in users
            if (u.cards_unprocessed and len(u.cards_unprocessed) > 0)
            or (
                hasattr(u, "national_id_card")
                and u.national_id_card
                and u.national_id_card.card_image_front
            )
        )
        users_without_cards = total_users - users_with_cards

        stats_data = [
            ["Total Users", str(total_users)],
            ["Users With Cards", str(users_with_cards)],
            ["Users Without Cards", str(users_without_cards)],
            ["Total Cards", str(total_cards)],
            ["Unprocessed Cards", str(total_unprocessed_cards)],
            ["National ID Cards", str(total_national_id_cards)],
            ["Report Date", get_this_moment().strftime("%Y-%m-%d")],
            ["Report Time", get_this_moment().strftime("%H:%M:%S")],
        ]

        stats_table = Table(stats_data, colWidths=[200, 100])
        stats_table.setStyle(
            TableStyle(
                [
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, -1), "notosans-hk-bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )

        story.append(stats_table)
        story.append(Spacer(1, 40))

        return story

    async def _create_user_pages(self, user: User) -> List:
        """Create detailed pages for a specific user"""
        story = []

        # User header page
        story.extend(self._create_user_header(user))
        story.append(PageBreak())

        # Cards display pages (including National ID as Card #1)
        cards_pages = await self._create_cards_display_pages(user)
        story.extend(cards_pages)

        return story

    async def _create_national_id_section(self, user: User) -> List:
        """Create section for National ID card display"""
        story = []

        try:
            # Section title
            national_id_title = Paragraph(
                "National ID Card",
                ParagraphStyle(
                    "NationalIDTitle",
                    parent=self.styles["Heading3"],
                    fontSize=16,
                    spaceAfter=15,
                    alignment=TA_CENTER,
                    fontName="notosans-hk-bold",
                    textColor=colors.darkblue,
                ),
            )
            story.append(national_id_title)

            # Try to decode and display the national ID card image
            if user.national_id_card.card_image_front:
                try:
                    # Decode base64 image
                    image_data = base64.b64decode(
                        user.national_id_card.card_image_front
                    )
                    image_stream = BytesIO(image_data)

                    # Create image object
                    national_id_img = Image(
                        image_stream, width=300, height=200, kind="proportional"
                    )

                    # Center the image in a table
                    image_table = Table([[national_id_img]], colWidths=[400])
                    image_table.setStyle(
                        TableStyle(
                            [
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
                                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                                ("TOPPADDING", (0, 0), (-1, -1), 10),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                            ]
                        )
                    )

                    story.append(image_table)

                except Exception as img_error:
                    logger.warning(
                        f"Could not process national ID image for user {user.mobile}: {str(img_error)}"
                    )
                    # Add error message instead of image
                    error_para = Paragraph(
                        "National ID Card image could not be displayed",
                        ParagraphStyle(
                            "ErrorMessage",
                            parent=self.styles["Normal"],
                            fontSize=12,
                            alignment=TA_CENTER,
                            fontName="notosans-hk-regular",
                            textColor=colors.red,
                        ),
                    )
                    story.append(error_para)

            # Add national ID information if available
            if hasattr(user, "national_id_no") and user.national_id_no:
                id_info = Paragraph(
                    f"National ID No: {user.national_id_no}",
                    ParagraphStyle(
                        "IDInfo",
                        parent=self.styles["Normal"],
                        fontSize=10,
                        alignment=TA_CENTER,
                        fontName="notosans-hk-regular",
                    ),
                )
                story.append(Spacer(1, 10))
                story.append(id_info)

        except Exception as e:
            logger.error(
                f"Error creating national ID section for user {user.mobile}: {str(e)}"
            )
            error_para = Paragraph(
                f"Error displaying National ID card: {str(e)}",
                ParagraphStyle(
                    "ErrorMessage",
                    parent=self.styles["Normal"],
                    fontSize=10,
                    alignment=TA_CENTER,
                    fontName="notosans-hk-regular",
                    textColor=colors.red,
                ),
            )
            story.append(error_para)

        return story

    async def _create_cards_display_pages(self, user: User) -> List:
        """Create pages showing all cards (National ID + unprocessed cards) in grids of 6 per page"""
        story = []

        # Combine National ID card (as Card #1) with unprocessed cards
        all_card_ids = []

        # Add National ID as first card if available
        if (
            hasattr(user, "national_id_card")
            and user.national_id_card
            and user.national_id_card.card_image_front
        ):
            all_card_ids.append("national_id")  # Special identifier for National ID

        # Add unprocessed cards
        if user.cards_unprocessed:
            all_card_ids.extend(user.cards_unprocessed)

        if not all_card_ids:
            # No cards to display - show basic user information table instead
            no_cards_para = Paragraph(
                "No cards available for this user",
                ParagraphStyle(
                    "NoCards",
                    parent=self.styles["Normal"],
                    fontSize=14,
                    alignment=TA_CENTER,
                    fontName="notosans-hk-regular",
                    textColor=colors.gray,
                ),
            )
            story.append(no_cards_para)
            story.append(Spacer(1, 20))

            # Add detailed user information table
            user_details_data = []

            # Basic information
            if hasattr(user, "english_name") and user.english_name:
                user_details_data.append(["English Name", user.english_name])
            if hasattr(user, "chinese_name") and user.chinese_name:
                user_details_data.append(["Chinese Name", user.chinese_name])
            if hasattr(user, "mobile") and user.mobile:
                user_details_data.append(["Mobile", user.mobile])
            if hasattr(user, "email") and user.email:
                user_details_data.append(["Email", user.email])
            if hasattr(user, "occupation") and user.occupation:
                user_details_data.append(["Occupation", user.occupation])
            if hasattr(user, "address") and user.address:
                user_details_data.append(["Address", user.address])
            if hasattr(user, "national_id_no") and user.national_id_no:
                user_details_data.append(["National ID No", user.national_id_no])
            if hasattr(user, "over_65"):
                user_details_data.append(
                    ["Age Over 65", "Yes" if user.over_65 else "No"]
                )
            if hasattr(user, "emergency_contact_name") and user.emergency_contact_name:
                user_details_data.append(
                    ["Emergency Contact", user.emergency_contact_name]
                )
            if (
                hasattr(user, "emergency_contact_phone")
                and user.emergency_contact_phone
            ):
                user_details_data.append(
                    ["Emergency Phone", user.emergency_contact_phone]
                )
            if hasattr(user, "created_at") and user.created_at:
                user_details_data.append(
                    ["Created At", user.created_at.strftime("%Y-%m-%d %H:%M:%S")]
                )

            # Create the detailed info table
            if user_details_data:
                details_table = Table(user_details_data, colWidths=[150, 350])
                details_table.setStyle(
                    TableStyle(
                        [
                            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                            ("ALIGN", (1, 0), (1, -1), "LEFT"),
                            ("FONTNAME", (0, 0), (0, -1), "notosans-hk-bold"),
                            ("FONTNAME", (1, 0), (1, -1), "notosans-hk-regular"),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                            ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
                            ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                        ]
                    )
                )
                story.append(details_table)

            return story

        # Split cards into chunks of 6
        for i in range(0, len(all_card_ids), 6):
            chunk = all_card_ids[i : i + 6]

            # Make grid table for this chunk
            grid_data = []
            for row_start in range(0, len(chunk), 2):  # 2 per row
                row = []
                for col in range(2):
                    idx = row_start + col
                    if idx < len(chunk):
                        card_data = await self._get_card_display_data(
                            chunk[idx], user, i + idx + 1
                        )
                        row.append(card_data)
                    else:
                        row.append("")  # Empty cell
                grid_data.append(row)

            # Calculate the number of rows dynamically
            # Increase row height to accommodate OCR data
            num_rows = len(grid_data)
            row_heights = [250] * num_rows  # Increased from 180 to 250 to fit OCR data

            table = Table(grid_data, colWidths=[250, 250], rowHeights=row_heights)
            table.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )

            story.append(table)
            story.append(PageBreak())

        return story

    def _create_user_header(self, user: User) -> List:
        """Create the header section for a user"""
        story = []

        # User name as main title - handle missing attributes gracefully
        english_name = (
            user.english_name
            if hasattr(user, "english_name") and user.english_name
            else "Unknown"
        )
        chinese_name = (
            user.chinese_name
            if hasattr(user, "chinese_name") and user.chinese_name
            else "未知"
        )
        user_title = Paragraph(
            f"User: {english_name} ({chinese_name})", self.title_style
        )
        story.append(user_title)
        story.append(Spacer(1, 20))

        # User information table with safe attribute access
        user_info_data = [
            [
                "Mobile Number",
                user.mobile if hasattr(user, "mobile") and user.mobile else "N/A",
            ],
            [
                "Occupation",
                (
                    user.occupation
                    if hasattr(user, "occupation") and user.occupation
                    else "N/A"
                ),
            ],
            [
                "Address",
                user.address if hasattr(user, "address") and user.address else "N/A",
            ],
            [
                "Age Over 65",
                "Yes" if hasattr(user, "over_65") and user.over_65 else "No",
            ],
            [
                "Emergency Contact",
                f"{user.emergency_contact_name if hasattr(user, 'emergency_contact_name') and user.emergency_contact_name else 'N/A'} "
                f"({user.emergency_contact_phone if hasattr(user, 'emergency_contact_phone') and user.emergency_contact_phone else 'N/A'})",
            ],
            [
                "User Created",
                (
                    user.created_at.strftime("%B %d, %Y at %I:%M %p")
                    if hasattr(user, "created_at") and user.created_at
                    else "N/A"
                ),
            ],
        ]

        user_info_table = Table(user_info_data, colWidths=[150, 200])
        user_info_table.setStyle(
            TableStyle(
                [
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "notosans-hk-bold"),
                    ("FONTNAME", (0, 1), (0, -1), "notosans-hk-bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.lightgrey, colors.white],
                    ),
                ]
            )
        )

        story.append(user_info_table)
        story.append(Spacer(1, 20))

        # Total cards count (including national ID if available)
        unprocessed_count = len(user.cards_unprocessed or [])
        national_id_count = (
            1
            if hasattr(user, "national_id_card")
            and user.national_id_card
            and user.national_id_card.card_image_front
            else 0
        )
        total_cards = unprocessed_count + national_id_count

        # Different styling based on whether user has cards
        if total_cards > 0:
            count_para = Paragraph(f"Total Cards: {total_cards}", self.card_count_style)
        else:
            count_para = Paragraph(
                "No Cards Available",
                ParagraphStyle(
                    "NoCardsCount", parent=self.card_count_style, textColor=colors.gray
                ),
            )
        story.append(count_para)

        return story

    async def _create_cards_grid(self, card_ids: List[str], user: User) -> Table:
        """Create a grid layout for displaying cards"""
        try:
            grid_data = []

            # Process cards in pairs (2 columns)
            for i in range(0, len(card_ids), 2):
                row = []

                # First card in row
                if i < len(card_ids):
                    card1_data = await self._get_card_display_data(
                        card_ids[i], user, i + 1
                    )
                    row.append(card1_data)
                else:
                    row.append("")

                # Second card in row
                if i + 1 < len(card_ids):
                    card2_data = await self._get_card_display_data(
                        card_ids[i + 1], user, i + 2
                    )
                    row.append(card2_data)
                else:
                    row.append("")

                grid_data.append(row)

            # Create table with proper column widths
            card_table = Table(grid_data, colWidths=[250, 250])
            card_table.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )

            return card_table

        except Exception as e:
            logger.error(f"Error creating cards grid: {str(e)}")
            # Return error message as table
            error_data = [["Error displaying cards", str(e)]]
            error_table = Table(error_data)
            error_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.red),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ]
                )
            )
            return error_table

    async def _get_card_display_data(
        self, card_id: str, user: User, card_number: int
    ) -> List:
        """Get display data for a single card (including National ID or GridFS cards)"""
        try:
            # Handle National ID card specially
            if card_id == "national_id":
                return await self._get_national_id_display_data(user, card_number)

            # Handle GridFS cards (unprocessed cards)
            grid_fs = await get_grid_fs()
            ocr_data = None

            try:
                object_id = ObjectId(card_id)
                grid_out = await grid_fs.open_download_stream(object_id)
                image_data = await grid_out.read()

                ocr_data = process_worker_card_ocr(image_data)
                logger.info(f"OCR data extracted successfully for card {ocr_data}")

                # Create image object with proper error handling
                try:
                    image_stream = BytesIO(image_data)
                    img = Image(
                        image_stream, width=200, height=150, kind="proportional"
                    )

                    # Create card info with OCR data if available
                    card_content = [img]

                    # Add basic card number
                    card_number_para = Paragraph(
                        f"Card #{card_number}",
                        ParagraphStyle(
                            "CardInfo",
                            parent=self.styles["Normal"],
                            fontSize=10,
                            alignment=TA_CENTER,
                            fontName="notosans-hk-bold",
                        ),
                    )
                    card_content.append(card_number_para)

                    # Add OCR extracted data if available
                    if ocr_data:
                        ocr_info_style = ParagraphStyle(
                            "OCRInfo",
                            parent=self.styles["Normal"],
                            fontSize=8,
                            alignment=TA_LEFT,
                            fontName="notosans-hk-regular",
                        )

                        # Add each piece of OCR data
                        if ocr_data.get("card_name"):
                            card_content.append(
                                Paragraph(
                                    f"Card: {ocr_data['card_name']}", ocr_info_style
                                )
                            )

                        if ocr_data.get("owner_name"):
                            card_content.append(
                                Paragraph(
                                    f"Name: {ocr_data['owner_name']}", ocr_info_style
                                )
                            )

                        if ocr_data.get("registration_no"):
                            card_content.append(
                                Paragraph(
                                    f"Reg #: {ocr_data['registration_no']}",
                                    ocr_info_style,
                                )
                            )

                        if ocr_data.get("issue_date"):
                            card_content.append(
                                Paragraph(
                                    f"Issued: {ocr_data['issue_date']}", ocr_info_style
                                )
                            )

                        if ocr_data.get("expiry_date"):
                            card_content.append(
                                Paragraph(
                                    f"Expires: {ocr_data['expiry_date']}",
                                    ocr_info_style,
                                )
                            )

                        if ocr_data.get("principal_trade_division"):
                            card_content.append(
                                Paragraph(
                                    f"Principal Trade Division: {ocr_data['principal_trade_division']}",
                                    ocr_info_style,
                                )
                            )

                        if ocr_data.get("other_trade_divisions"):
                            card_content.append(
                                Paragraph(
                                    f"Other Trade Divisions: {ocr_data['other_trade_divisions']}",
                                    ocr_info_style,
                                )
                            )

                    return card_content

                except Exception as img_error:
                    logger.warning(
                        f"Could not process image for card {card_id}: {str(img_error)}"
                    )
                    # Return text-only version with OCR data if available
                    return self._create_text_only_card_display(
                        card_number, card_id, user, ocr_data
                    )

            except Exception as e:
                logger.warning(f"Could not load image for card {card_id}: {str(e)}")
                # Return text-only version
                return self._create_text_only_card_display(card_number, card_id, user)

        except Exception as e:
            logger.error(f"Error processing card {card_id}: {str(e)}")
            return self._create_error_card_display(card_number, str(e))

    async def _get_national_id_display_data(self, user: User, card_number: int) -> List:
        """Get display data specifically for National ID card"""
        try:
            if not (user.national_id_card and user.national_id_card.card_image_front):
                return self._create_error_card_display(
                    card_number, "National ID card not available"
                )

            # Decode base64 image
            image_data = base64.b64decode(user.national_id_card.card_image_front)
            image_stream = BytesIO(image_data)

            # Create image object
            img = Image(image_stream, width=200, height=150, kind="proportional")

            # Create card content
            card_content = [img]

            # Add card number and type
            card_number_para = Paragraph(
                f"Card #{card_number} - National ID",
                ParagraphStyle(
                    "CardInfo",
                    parent=self.styles["Normal"],
                    fontSize=10,
                    alignment=TA_CENTER,
                    fontName="notosans-hk-bold",
                    textColor=colors.darkblue,
                ),
            )
            card_content.append(card_number_para)

            # Add user info
            info_style = ParagraphStyle(
                "NationalIDInfo",
                parent=self.styles["Normal"],
                fontSize=8,
                alignment=TA_LEFT,
                fontName="notosans-hk-regular",
            )

            if user.national_id_no:
                card_content.append(
                    Paragraph(f"ID No: {user.national_id_no}", info_style)
                )

            if user.english_name:
                card_content.append(Paragraph(f"Name: {user.english_name}", info_style))

            if user.chinese_name:
                card_content.append(
                    Paragraph(f"中文名: {user.chinese_name}", info_style)
                )

            return card_content

        except Exception as e:
            logger.error(
                f"Error processing National ID for user {user.mobile}: {str(e)}"
            )
            return self._create_error_card_display(
                card_number, f"Error displaying National ID: {str(e)}"
            )

    def _create_text_only_card_display(
        self,
        card_number: int,
        card_id: str,
        user: User,
        ocr_data: Optional[Dict[str, Any]] = None,
    ) -> List:
        """Create a text-only display when image is not available"""
        result = [
            Paragraph(f"Card #{card_number}", self.styles["Heading3"]),
            Paragraph(f"ID: {card_id[:8]}...", self.styles["Normal"]),
            Paragraph("Image not available", self.styles["Normal"]),
            Paragraph(f"User: {user.english_name}", self.styles["Normal"]),
            Paragraph(f"Mobile: {user.mobile}", self.styles["Normal"]),
        ]

        # Add OCR data if available
        if ocr_data:
            ocr_info_style = ParagraphStyle(
                "OCRInfo",
                parent=self.styles["Normal"],
                fontSize=8,
                alignment=TA_LEFT,
                fontName="notosans-hk-regular",
            )

            if ocr_data.get("card_name"):
                result.append(
                    Paragraph(f"Card: {ocr_data['card_name']}", ocr_info_style)
                )

            if ocr_data.get("owner_name"):
                result.append(
                    Paragraph(f"Name: {ocr_data['owner_name']}", ocr_info_style)
                )

            if ocr_data.get("registration_no"):
                result.append(
                    Paragraph(f"Reg #: {ocr_data['registration_no']}", ocr_info_style)
                )

            if ocr_data.get("issue_date"):
                result.append(
                    Paragraph(f"Issued: {ocr_data['issue_date']}", ocr_info_style)
                )

            if ocr_data.get("expiry_date"):
                result.append(
                    Paragraph(f"Expires: {ocr_data['expiry_date']}", ocr_info_style)
                )

        return result

    def _create_error_card_display(self, card_number: int, error_msg: str) -> List:
        """Create an error display when card processing fails"""
        return [
            Paragraph(f"Card #{card_number}", self.styles["Heading3"]),
            Paragraph("Error loading card", self.styles["Normal"]),
            Paragraph(error_msg, self.styles["Normal"]),
        ]

    def _generate_empty_pdf(self) -> bytes:
        """Generate a PDF when no users are found"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        story = []

        # Title
        title = Paragraph("User Cards Report", self.title_style)
        story.append(title)
        story.append(Spacer(1, 50))

        # Message
        message = Paragraph(
            "No active users found in the system.",
            ParagraphStyle(
                "EmptyMessage",
                parent=self.styles["Normal"],
                fontSize=16,
                alignment=TA_CENTER,
                fontName="notosans-hk-regular",
            ),
        )
        story.append(message)
        story.append(Spacer(1, 30))

        # Additional info
        info = Paragraph(
            "There are no active users in the database. Please create users before generating this report.",
            ParagraphStyle(
                "Info",
                parent=self.styles["Normal"],
                fontSize=12,
                alignment=TA_CENTER,
                fontName="notosans-hk-regular",
            ),
        )
        story.append(info)

        doc.build(story)
        buffer.seek(0)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        return pdf_bytes


# Convenience function for easy usage
async def generate_unprocessed_cards_pdf(output_path: str = None) -> bytes:
    """
    Convenience function to generate unprocessed cards PDF

    Args:
        output_path: Optional path to save the PDF file

    Returns:
        PDF content as bytes
    """
    generator = UnprocessedCardsPDFGenerator()
    return await generator.generate_unprocessed_cards_pdf(output_path)
