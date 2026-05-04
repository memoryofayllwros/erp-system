from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

output_path = "works_permit_complete.pdf"

doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    rightMargin=20 * mm,
    leftMargin=20 * mm,
    topMargin=20 * mm,
    bottomMargin=20 * mm,
)

styles = getSampleStyleSheet()
styleN = styles["Normal"]
styleB = styles["BodyText"]
styleBH = styles["Heading2"]
styleTitle = styles["Title"]
styleI = styles["Italic"]

story = []


# --- Page 1 ---
def add_first_page(
    project_code: str,
    project_title: str,
    project_location: str,
    works_order_no: str,
    works_site: str,
    start_date: date,
    end_date: date,
    contact_person: str,
    contact_mobile: str,
):

    # Create the table data with the header as the first row

    centered_title_style = ParagraphStyle(
        "Title",
        parent=styles["Normal"],
        fontSize=14,
        fontName="notosans-hk-bold",
        spaceAfter=5,
        alignment=1,  # 1 = center alignment
    )

    # Title section with centered text
    story.append(
        Paragraph("<font size=14><b>Works Permit</b></font>", centered_title_style)
    )
    story.append(
        Paragraph(
            "<font size=14>for Contractor Carrying Out Works at</font>",
            centered_title_style,
        )
    )
    story.append(
        Paragraph(
            f"<font size=14><b>{project_location}</b></font>", centered_title_style
        )
    )
    story.append(Spacer(1, 15))

    header_style = ParagraphStyle(
        "Header",
        parent=styles["Normal"],
        fontSize=12,
        fontName="notosans-hk-bold",
        alignment=0,  # Left alignment
    )

    details_style = ParagraphStyle(
        "ProjectDetails",
        parent=styles["Normal"],
        fontSize=10,
        fontName="notosans-hk-regular",
        alignment=0,  # Left alignment
    )

    start_date_str = start_date.strftime("%d/%m/%Y") if start_date else ""
    end_date_str = end_date.strftime("%d/%m/%Y") if end_date else ""

    data = [
        [
            Paragraph(
                "Project Particulars (to be completed by the Contractor)", header_style
            ),
            "",
        ],
        [
            Paragraph("<b>Project Title:</b>", details_style),
            Paragraph(f"{project_title}", details_style),
        ],
        [
            Paragraph("<b>Works Order No.:</b>", details_style),
            Paragraph(f"{works_order_no}", details_style),
        ],
        [
            Paragraph("<b>Name of Contractor</b>", details_style),
            Paragraph("GCB Construction Limited", details_style),
        ],
        [
            Paragraph("<b>Works Agent</b>", details_style),
            Paragraph("HA", details_style),
        ],
        [
            Paragraph("<b>Works site</b>", details_style),
            Paragraph(f"{works_site}", details_style),
        ],
        [
            Paragraph("<b>Works Duration</b>", details_style),
            Paragraph(f"From: {start_date_str}      To: {end_date_str}", details_style),
        ],
        [
            Paragraph("<b>Daily Working Hours</b>", details_style),
            Paragraph(f"From: 9:00 (am/pm)       To: 05:30 (am/pm)", details_style),
        ],
        [
            Paragraph("<b>Suspension of Building Services Requried</b>", details_style),
            Paragraph("*N", details_style),
        ],
        [
            Paragraph("<b>Contact Person</b>", details_style),
            Paragraph(
                f"{contact_person} (Site Agent)       Mobile No : {contact_mobile}",
                details_style,
            ),
        ],
    ]

    # Create and style the table
    table = Table(data, colWidths=[65 * mm, 120 * mm])
    table_style = TableStyle(
        [
            (
                "GRID",
                (0, 1),
                (-1, -1),
                1,
                colors.black,
            ),  # Grid for all cells except header
            ("SPAN", (0, 0), (1, 0)),  # Header spans both columns
            (
                "BACKGROUND",
                (0, 0),
                (1, 0),
                colors.lightgrey,
            ),  # Grey background for header
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (-1, -1), "notosans-hk-regular"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
        ]
    )
    table.setStyle(table_style)
    story.append(table)
    story.append(Spacer(1, 15))

    # Approval text
    story.append(
        Paragraph(
            "Approval is hereby granted to the Contractor to carry out the works in the area(s) within the period as specified in the above description of works.",
            details_style,
        )
    )

    # Space for signature
    story.append(Spacer(1, 50))

    # Signature line and date
    sig_data = [["", ""], ["Date:", "Signature"], ["* delete as appropriate", ""]]

    sig_table = Table(sig_data, colWidths=[80 * mm, 80 * mm])
    sig_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, -1), "notosans-hk-regular"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LINEABOVE", (1, 1), (1, 1), 1, colors.black),
            ]
        )
    )
    story.append(sig_table)

    # Horizontal line
    story.append(Spacer(1, 10))
    hline = Table([[""]], colWidths=[170 * mm], rowHeights=[1])
    hline.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 1, colors.black)]))
    story.append(hline)

    # Notes section
    story.append(Paragraph("<b>Note:</b>", details_style))
    notes = [
        "1) No Contractor and/or his workers is allowed to work in the area without a valid works permit.",
        "2) Application for works permit must be submitted to Facilities Management Division, at least 5 working days before commencement of site works. Application for extension of works permit should be made by the Contractor if required.",
        "3) The attached worker list must be duly completed in association with works permit. Revised workers list must be submitted for any change of workers deployed for project.",
        "4) The contractor and his workers shall strictly comply with the requirements as stipulated in the House Rule for Contractor/Worker working in the area as attached.",
    ]

    note_style = ParagraphStyle(
        "Notes",
        parent=styleI,
        fontSize=10,
        fontName="notosans-hk-regular",
        leftIndent=10,
        firstLineIndent=-10,
        leading=14,
    )

    footer_style = ParagraphStyle(
        "Footer",
        parent=styleI,
        fontSize=9,
        fontName="notosans-hk-regular",
        leftIndent=0,
    )

    for note in notes:
        story.append(Paragraph(note, note_style))

    # Footer text
    story.append(Spacer(1, 5))
    story.append(Paragraph("c.c FMO/ EMSD/ Arch.S.D/HAHO", footer_style))
    story.append(Spacer(1, 5))
    story.append(Paragraph("CCH Works Permit (version 5)", footer_style))

    story.append(PageBreak())
