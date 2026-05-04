import logging
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from src.models.project_model import Project
from src.models.user_model import User
from src.pdf_templates.work_permit_pdf.part_1_project_info import \
    add_first_page
from src.pdf_templates.work_permit_pdf.part_1_project_info import \
    story as story1
from src.pdf_templates.work_permit_pdf.part_2_workers_list import \
    add_second_page
from src.pdf_templates.work_permit_pdf.part_2_workers_list import \
    story as story2
from src.pdf_templates.work_permit_pdf.part_3_house_rules import add_third_page
from src.pdf_templates.work_permit_pdf.part_3_house_rules import \
    story as story3
from src.pdf_templates.work_permit_pdf.part_4_workers_card import \
    add_fourth_page
from src.pdf_templates.work_permit_pdf.part_4_workers_card import \
    story as story4
from assets.fonts.font_utils import register_fonts


async def generate_work_permit_pdf(project_code: str) -> bytes:

    logging.info(f"Starting PDF generation for project {project_code}")

    # Register fonts before generating PDF
    register_fonts()
    logging.info("Fonts registered successfully")

    project_info = await Project.find_one(
        Project.project_code == project_code, Project.deleted_at == None
    )

    project_location = project_info.project_title

    # Find all workers for this project
    workers = await User.find(
        User.project_code == project_code, User.deleted_at == None
    ).to_list()

    # Get workers who have at least one type of card
    workers_with_cards = [
        w for w in workers if w.construction_worker_card or w.certified_worker_card
    ]

    logging.info(f"Found {len(workers)} total workers for project {project_code}")
    logging.info(
        f"Found {len(workers_with_cards)} workers with cards for project {project_code}"
    )

    # Continue even if no workers with cards, but we need at least one worker
    if not workers:
        logging.warning(f"No workers found for project {project_code}")

    output_path = f"works_permit_{project_code}.pdf"
    logging.info(f"Will save temporary PDF to {output_path}")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    # Clear any existing content in story lists
    story1.clear()
    story2.clear()
    story3.clear()
    story4.clear()

    # Generate first three pages
    logging.info("Generating first page (project info)")
    add_first_page(project_code, project_location)

    logging.info("Generating second page (workers list)")
    add_second_page(workers_with_cards)  # Updated to handle multiple workers

    logging.info("Generating third page (house rules)")
    add_third_page()

    # Generate a card page for each worker
    logging.info("Generating worker card pages")
    if workers and len(workers) > 0:
        for i, worker in enumerate(workers):
            logging.info(f"Processing worker {i+1}/{len(workers)}: {worker.user_name}")
            try:
                # Properly await the async function
                await add_fourth_page(worker)
            except Exception as e:
                logging.error(
                    f"Error generating card page for worker {worker.user_name}: {str(e)}"
                )
                logging.error(f"Continuing without this worker's card")
    else:
        logging.warning("No workers found to generate cards for")

    # Combine all stories
    complete_story = []
    complete_story.extend(story1 if story1 else [])
    complete_story.extend(story2 if story2 else [])
    complete_story.extend(story3 if story3 else [])
    complete_story.extend(story4 if story4 else [])

    logging.info(f"Combined story has {len(complete_story)} elements")

    # Build the document
    logging.info("Building PDF document")
    try:
        doc.build(complete_story)
        logging.info("PDF document built successfully")
    except Exception as e:
        logging.error(f"Error building PDF document: {str(e)}")
        raise

    # Read the file as bytes and return
    try:
        with open(output_path, "rb") as f:
            pdf_content = f.read()

        pdf_size = len(pdf_content)
        logging.info(f"PDF generated successfully, size: {pdf_size} bytes")

        # Clean up the temporary file
        if os.path.exists(output_path):
            os.remove(output_path)
            logging.info(f"Temporary file {output_path} removed")

        return pdf_content
    except Exception as e:
        logging.error(f"Error reading or cleaning up PDF file: {str(e)}")
        raise
