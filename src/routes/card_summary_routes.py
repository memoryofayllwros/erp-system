import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter()

logger = logging.getLogger(__name__)

from src.utils.datetime_standarization_helpers import get_this_moment

@router.get("/user/unprocessed-cards-pdf-report")
async def generate_unprocessed_cards_pdf_report():
    """Generate and download a comprehensive PDF report of all unprocessed cards"""
    try:
        from src.pdf_templates.unprocessed_cards_pdf.unprocessed_cards_generator import \
            generate_unprocessed_cards_pdf

        # Generate the PDF
        pdf_bytes = await generate_unprocessed_cards_pdf()

        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="Failed to generate PDF")

        # Create filename with timestamp
        timestamp = get_this_moment().strftime("%Y%m%d_%H%M%S")
        filename = f"unprocessed_cards_report_{timestamp}.pdf"

        # Return PDF as downloadable file
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating unprocessed cards PDF report: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
