import logging
import os

import aiohttp
from aiohttp import BasicAuth
from dotenv import load_dotenv
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account

load_dotenv()

account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")

# extract work permit
SERVICE_ACCOUNT_JSON = os.environ.get("WORK_PERMIT_DOCUMENTAI_CREDENTIALS")
if not SERVICE_ACCOUNT_JSON:
    raise RuntimeError(
        "Set WORK_PERMIT_DOCUMENTAI_CREDENTIALS to the service account JSON path "
        "(copy from .env.example; file must not be committed)."
    )
PROJECT_ID = "projectbao-virpluz"
LOCATION = "us"
PROCESSOR_ID = "31512747157ad4fb"
# extract work permit

# Authenticate
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_JSON
)

# Create a client
client = documentai.DocumentProcessorServiceClient(credentials=credentials)
name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"


def process_worker_card_ocr(image_bytes: bytes) -> dict:
    document = {"content": image_bytes, "mime_type": "image/jpeg"}
    request = {"name": name, "raw_document": document}
    result = client.process_document(request=request)

    extracted_data = {}
    for entity in result.document.entities:
        field_name = entity.type_.lower().replace(" ", "_")
        field_value = entity.mention_text.strip()
        extracted_data[field_name] = field_value

    return extracted_data


async def download_image_to_memory(media_url: str) -> bytes:
    if not media_url:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                media_url, auth=BasicAuth(account_sid, auth_token), timeout=30
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logging.error(
                        f"Failed to fetch media. Status: {response.status}, Response: {error_text}"
                    )
                    return None

                # Read data into memory
                data = await response.read()

                if not data:
                    logging.error("No data received from media URL")
                    return None

                # Verify content type
                content_type = response.headers.get("content-type", "").lower()
                logging.info(
                    f"Received content type: '{content_type}' (length: {len(content_type)})"
                )

                # Accept both images and PDFs
                if not content_type.startswith("image/"):
                    logging.error(
                        f"Unsupported content type: '{content_type}' (starts with image/: {content_type.startswith('image/')})"
                    )
                    return None

                logging.info(
                    f"Successfully downloaded media ({content_type}), size: {len(data)} bytes"
                )
                return data

    except aiohttp.ClientResponseError as e:
        logging.error(f"HTTP error fetching media: {e.status} - {e.message}")
    except aiohttp.ClientTimeout:
        logging.error("Request timed out while fetching media.")
    except Exception as e:
        logging.error(f"Unexpected error downloading media: {str(e)}", exc_info=True)

    return None


async def extract_work_permit_info_from_media(url: str) -> dict:
    try:
        image_bytes = await download_image_to_memory(url)
        if image_bytes is None:
            raise ValueError("Failed to download image")

        result = process_worker_card_ocr(image_bytes)

        return result

    except Exception as e:
        logging.error(f"Error in OCR processing from URL: {str(e)}")
        raise ValueError(f"Error in OCR processing: {str(e)}")
