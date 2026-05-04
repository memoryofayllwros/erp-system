import base64
import io
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, PageBreak, Paragraph, Spacer, Table,
                                TableStyle)

from src.models.user_model import User

story = []


async def add_fourth_page(worker: User, sequence_number: int = 1):
    logging.info(f"Adding fourth page for worker {worker.chinese_name}")
    styles = getSampleStyleSheet()

    # Create custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontName="notosans-hk-bold",
        fontSize=16,
        spaceAfter=10,
        alignment=1,  # Center alignment
    )

    worker_code_style = ParagraphStyle(
        "WorkerCode",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=18,
        spaceAfter=0,
    )

    worker_name_title_style = ParagraphStyle(
        "WorkerNameTitle",
        parent=styles["Normal"],
        fontName="notosans-hk-bold",
        fontSize=14,
        spaceAfter=0,
        alignment=2,  # Right alignment
    )

    worker_name_style = ParagraphStyle(
        "WorkerName",
        parent=styles["Normal"],
        fontName="notosans-hk-bold",
        fontSize=14,
        spaceAfter=0,
        alignment=0,  # Left alignment
    )

    cell_header_style = ParagraphStyle(
        "CellHeader",
        parent=styles["Normal"],
        fontName="notosans-hk-bold",
        fontSize=10,
        alignment=0,  # Left alignment
    )

    detail_style = ParagraphStyle(
        "DetailText",
        parent=styles["Normal"],
        fontName="notosans-hk-regular",
        fontSize=10,
    )

    # Page title
    story.append(Paragraph("GCB Construction Limited -- 工人証", title_style))
    story.append(Spacer(1, 10))

    # Worker code and name as a table with a line under the name
    code_name_data = [
        [
            Paragraph(f"BW - {sequence_number}", worker_code_style),
            Paragraph(f"姓名: ", worker_name_title_style),
            Paragraph(f"{worker.worker_name}", worker_name_style),
        ]
    ]

    # Column widths: BW code, "姓名:", worker name
    code_name_table = Table(code_name_data, colWidths=[110 * mm, 30 * mm, 60 * mm])
    code_name_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "LINEBELOW",
                    (2, 0),
                    (2, 0),
                    1,
                    (0, 0, 0),
                ),  # Line only under the worker name
            ]
        )
    )

    story.append(code_name_table)
    story.append(Spacer(1, 15))

    # Create data for the main table
    table_rows = []

    # ROW 1 - Headers (4 cells with specific widths and no bottom border for 2nd and 4th cells)
    row1 = [
        Paragraph("建造業工人註冊証", cell_header_style),  # Cell 1 - 55.5mm
        Paragraph("", detail_style),  # Cell 2 - 39.5mm - no bottom border
        Paragraph("建築業工人註冊証咭序號", cell_header_style),  # Cell 3 - 55.5mm
        Paragraph("", detail_style),  # Cell 4 - 39.5mm - no bottom border
    ]
    table_rows.append(row1)

    # ROW 2 - Construction worker card image (needs 4 cells total for the table)
    row2 = []
    if worker.construction_worker_card and worker.construction_worker_card:
        try:
            image_bytes = base64.b64decode(
                worker.construction_worker_card.card_image_front
            )
            image_stream = io.BytesIO(image_bytes)
            img = Image(image_stream, width=90 * mm, height=55 * mm)
            row2.append(img)
        except Exception as e:
            row2.append(Paragraph("Image not available", detail_style))
    else:
        row2.append(Paragraph("", detail_style))

    # Empty cell that will be part of the span
    row2.append(Paragraph("", detail_style))

    # Right side empty cells (will be spanned)
    row2.append(Paragraph("", detail_style))
    row2.append(Paragraph("", detail_style))

    table_rows.append(row2)

    # ROW 3 - Card details (exactly 4 cells)
    row3 = []
    # Construction worker card details - first 2 cells
    if worker.construction_worker_card and worker.construction_worker_card:
        row3.append(
            Paragraph(
                f"號碼:    {worker.construction_worker_card.registration_no}",
                cell_header_style,
            )
        )
        row3.append(
            Paragraph(
                f"到期日:    {worker.construction_worker_card.expiry_date.strftime('%d-%m-%Y')}",
                cell_header_style,
            )
        )
    else:
        row3.append(Paragraph("", detail_style))
        row3.append(Paragraph("", detail_style))

    # Work type and card sequence cells - last 2 cells
    row3.append(Paragraph("工種編號", cell_header_style))
    row3.append(Paragraph("咭序號", cell_header_style))
    table_rows.append(row3)

    # ROW 4 - Green card header (same structure as row 1)
    row4 = [
        Paragraph("平安咭", cell_header_style),  # Cell 1 - 55.5mm
        Paragraph("", detail_style),  # Cell 2 - 39.5mm - no bottom border
        Paragraph("", detail_style),  # Cell 3 - 55.5mm
        Paragraph("", detail_style),  # Cell 4 - 39.5mm - no bottom border
    ]
    table_rows.append(row4)

    # ROW 5 - Green card image (needs 4 cells total for the table)
    row5 = []
    # Green card image (will span 2 cells)
    if worker.certified_worker_card and worker.certified_worker_card:
        try:
            image_bytes = base64.b64decode(
                worker.certified_worker_card.card_image_front
            )
            image_stream = io.BytesIO(image_bytes)
            img = Image(image_stream, width=90 * mm, height=55 * mm)
            row5.append(img)
        except Exception as e:
            row5.append(Paragraph("Image not available", detail_style))
    else:
        row5.append(Paragraph("", detail_style))

    # Empty cell that will be part of the span
    row5.append(Paragraph("", detail_style))

    # Right side empty cells (will be spanned)
    row5.append(Paragraph("", detail_style))
    row5.append(Paragraph("", detail_style))

    table_rows.append(row5)

    # ROW 6 - Green card details (exactly 4 cells)
    row6 = []
    # Certified worker card details - first 2 cells
    if worker.certified_worker_card and worker.certified_worker_card:
        row6.append(
            Paragraph(
                f"號碼:    {worker.certified_worker_card.reference_no}",
                cell_header_style,
            )
        )
        row6.append(
            Paragraph(
                f"到期日:    {worker.certified_worker_card.expiry_date.strftime('%d-%m-%Y')}",
                cell_header_style,
            )
        )
    else:
        row6.append(Paragraph("", detail_style))
        row6.append(Paragraph("", detail_style))

    # Last 2 cells (will be spanned)
    row6.append(Paragraph("", detail_style))
    row6.append(Paragraph("", detail_style))
    table_rows.append(row6)

    # Create the table with exact column widths
    col_widths = [55.5 * mm, 39.5 * mm, 55.5 * mm, 39.5 * mm]
    row_heights = [8 * mm, 60 * mm, 7 * mm, 8 * mm, 60 * mm, 7 * mm]

    # Verify all rows have 4 cells to match the column count
    logging.info(
        f"Row counts: row1={len(row1)}, row2={len(row2)}, row3={len(row3)}, row4={len(row4)}, row5={len(row5)}, row6={len(row6)}"
    )

    main_table = Table(
        table_rows, colWidths=col_widths, rowHeights=row_heights, repeatRows=0
    )

    # Apply detailed styling with all the specific requirements
    main_table.setStyle(
        TableStyle(
            [
                # Grid for all cells
                ("GRID", (0, 0), (-1, -1), 1, (0, 0, 0)),
                # Remove bottom borders for specific cells in rows 1 and 4
                (
                    "LINEBELOW",
                    (1, 0),
                    (1, 0),
                    0,
                    (0, 0, 0),
                ),  # No bottom border for cell (1,0)
                (
                    "LINEBELOW",
                    (3, 0),
                    (3, 0),
                    0,
                    (0, 0, 0),
                ),  # No bottom border for cell (3,0)
                (
                    "LINEBELOW",
                    (1, 3),
                    (1, 3),
                    0,
                    (0, 0, 0),
                ),  # No bottom border for cell (1,3)
                (
                    "LINEBELOW",
                    (3, 3),
                    (3, 3),
                    0,
                    (0, 0, 0),
                ),  # No bottom border for cell (3,3)
                # Cell spans for headers
                (
                    "SPAN",
                    (0, 0),
                    (1, 0),
                ),  # Row 1: Span cells 0-1 for construction worker card header
                (
                    "SPAN",
                    (2, 0),
                    (3, 0),
                ),  # Row 1: Span cells 2-3 for registration number header
                ("SPAN", (0, 3), (1, 3)),  # Row 4: Span cells 0-1 for green card header
                ("SPAN", (2, 3), (3, 3)),  # Row 4: Span cells 2-3 for empty header
                # Cell spans for images
                (
                    "SPAN",
                    (0, 1),
                    (1, 1),
                ),  # Row 2: Span cells 0-1 for construction worker card image
                (
                    "SPAN",
                    (2, 1),
                    (3, 1),
                ),  # Row 2: Span cells 2-3 for the empty right side
                ("SPAN", (0, 4), (1, 4)),  # Row 5: Span cells 0-1 for green card image
                (
                    "SPAN",
                    (2, 4),
                    (3, 4),
                ),  # Row 5: Span cells 2-3 for the empty right side
                # Cell span for green card details
                (
                    "SPAN",
                    (2, 5),
                    (3, 5),
                ),  # Row 6: Span cells 2-3 for the empty right side
                # Vertical alignment
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # Padding
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    story.append(main_table)
    story.append(PageBreak())
    logging.info("Fourth page completed")
