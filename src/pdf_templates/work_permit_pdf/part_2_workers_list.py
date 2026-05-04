import logging
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from src.models.user_model import User

styles = getSampleStyleSheet()
styleN = styles["Normal"]
styleB = styles["BodyText"]
styleBH = styles["Heading2"]
styleTitle = styles["Title"]

story = []
# --- Page 2 ---


def add_second_page(workers: List[User]):

    # Add title
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=30,
        alignment=1,  # Center alignment
    )
    story.append(Paragraph("Workers List", title_style))
    story.append(Spacer(1, 20))

    # Check if we have workers with cards
    if workers and len(workers) > 0:
        # Create table data
        table_data = [
            [
                "No.",
                "工人姓名\nWorker Name",
                "註冊證\nConstruction Worker Card",
                "平安卡編號\nGreen Card",
                "其他工種\nOther Specialist",
            ]
        ]

        # Add worker data
        for worker in workers:
            registration_card_info = "✓" if worker.construction_worker_card else ""
            if worker.construction_worker_card:
                registration_card_info += (
                    f"\nReg No: {worker.construction_worker_card.registration_no}"
                )
                registration_card_info += f"\nExpiry: {worker.construction_worker_card.expiry_date.strftime('%d-%m-%Y')}"

            else:
                registration_card_info = " "

            certified_card_info = "✓" if worker.certified_worker_card else " "
            if worker.certified_worker_card:
                certified_card_info += (
                    f"\nRef No: {worker.certified_worker_card.reference_no}"
                )
                certified_card_info += f"\nExpiry: {worker.certified_worker_card.expiry_date.strftime('%d-%m-%Y')}"

            else:
                certified_card_info = " "

            table_data.append(
                [
                    # worker.bw_code,  # Assuming bw_code is a unique identifier
                    worker.chinese_name,
                    registration_card_info,
                    certified_card_info,
                    "✓",
                ]
            )

        # Create and style the table
        table = Table(
            table_data, colWidths=[15 * mm, 30 * mm, 55 * mm, 55 * mm, 35 * mm]
        )
        table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("FONTNAME", (0, 0), (-1, 0), "notosans-hk-bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("FONTNAME", (0, 1), (-1, -1), "notosans-hk-regular"),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)
    else:
        # Just display a message without a table
        message_style = ParagraphStyle(
            "Message",
            parent=styles["Normal"],
            fontSize=10,
            alignment=1,  # Center alignment
            spaceAfter=10,
        )
        story.append(Paragraph("No workers with any cards found", message_style))
        story.append(Spacer(1, 20))

    story.append(PageBreak())
