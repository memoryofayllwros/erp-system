import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi.responses import JSONResponse
from twilio.rest import Client

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")
chatbot_waba = os.getenv("WHATSAPP_NUMBER")
messaging_service_sid = os.getenv("MESSAGING_SERVICE_SID")

client = Client(account_sid, auth_token)

MAX_TWILIO_MSG_LENGTH = 1500


async def send_whatsapp_message_back(
    body_text: str | dict, recipient: str, media_url: str = None
):
    try:
        if not recipient:
            logger.error("Empty recipient provided")
            return JSONResponse(
                content={"status": "error", "message": "Empty recipient"},
                status_code=400,
            )

        # Ensure recipient has whatsapp: prefix
        if not recipient.startswith("whatsapp:"):
            recipient = f"whatsapp:{recipient}"

        # Handle dict-formatted input with metadata
        if isinstance(body_text, dict):
            meta = body_text.get("meta", {})
            message_text = body_text.get("text", "")
        else:
            meta = {}
            message_text = str(body_text)

        if media_url:
            message_text += f"\n\n📎 Download Link: {media_url}"

        logger.info(f"Preparing to send message to: {recipient}")
        logger.info(f"Using WhatsApp number: {chatbot_waba}")
        logger.info(f"Using messaging service SID: {messaging_service_sid}")

        message_params = {
            "from_": f"whatsapp:{chatbot_waba}",
            "to": recipient,
            "messaging_service_sid": messaging_service_sid,
        }

        message_sids = []

        # Chunk if too long - split at logical boundaries instead of arbitrary character limits
        if len(message_text) > MAX_TWILIO_MSG_LENGTH:
            chunks = []

            # Priority 1: Try to split by logical boundaries like double newlines, section headers, etc.
            logical_breaks = [
                "\n\n",  # Double newlines
                "\n---\n",  # Separator lines
                "\n===\n",  # Another separator
                "\n• ",  # Bullet points
            ]

            # Find the best break point
            best_break = None
            best_position = 0

            for break_pattern in logical_breaks:
                if break_pattern in message_text:
                    # Find the last occurrence before the character limit
                    pos = message_text.rfind(break_pattern, 0, MAX_TWILIO_MSG_LENGTH)
                    if pos > best_position:
                        best_position = pos + len(break_pattern)
                        best_break = break_pattern

            if best_break and best_position > 0:
                # Split at the logical break point
                first_chunk = message_text[:best_position].strip()
                remaining_text = message_text[best_position:].strip()

                chunks = [first_chunk]

                # Continue splitting remaining text if it's still too long
                while len(remaining_text) > MAX_TWILIO_MSG_LENGTH:
                    # Look for next logical break in remaining text
                    next_break_pos = 0
                    for break_pattern in logical_breaks:
                        pos = remaining_text.rfind(
                            break_pattern, 0, MAX_TWILIO_MSG_LENGTH
                        )
                        if pos > next_break_pos:
                            next_break_pos = pos + len(break_pattern)

                    if next_break_pos > 0:
                        chunks.append(remaining_text[:next_break_pos].strip())
                        remaining_text = remaining_text[next_break_pos:].strip()
                    else:
                        # No more logical breaks, try single newline chunking
                        break

                if remaining_text:
                    chunks.append(remaining_text)
            else:
                # Priority 2: Try single newline chunking
                single_newline_chunks = []
                current_chunk = ""
                lines = message_text.split("\n")

                for line in lines:
                    # Check if adding this line would exceed the limit
                    if (
                        len(current_chunk) + len(line) + 1 > MAX_TWILIO_MSG_LENGTH
                        and current_chunk
                    ):
                        # Current chunk is full, save it and start a new one
                        single_newline_chunks.append(current_chunk.strip())
                        current_chunk = line
                    else:
                        # Add to current chunk
                        if current_chunk:
                            current_chunk += "\n" + line
                        else:
                            current_chunk = line

                # Add the last chunk if it has content
                if current_chunk:
                    single_newline_chunks.append(current_chunk.strip())

                if single_newline_chunks:
                    chunks = single_newline_chunks
                else:
                    # Fallback: Character-based chunking if no logical breaks found
                    prefix_len = len("(X/Y) ")
                    max_chunk = MAX_TWILIO_MSG_LENGTH - prefix_len
                    chunks = [
                        message_text[i : i + max_chunk]
                        for i in range(0, len(message_text), max_chunk)
                    ]
        else:
            chunks = [message_text]

        for idx, chunk in enumerate(chunks):
            formatted_chunk = (
                f"({idx+1}/{len(chunks)}) {chunk}" if len(chunks) > 1 else chunk
            )
            logger.info(
                f"Sending chunk {idx+1}/{len(chunks)}: {len(formatted_chunk)} characters"
            )
            message_params["body"] = formatted_chunk
            try:
                msg = client.messages.create(**message_params)
                message_sids.append(msg.sid)
                logger.info(f"Message sent. SID: {msg.sid}, Status: {msg.status}")

                # Add 1 second delay before sending next chunk (except for the last chunk)
                if idx < len(chunks) - 1:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Failed to send chunk: {str(e)}", exc_info=True)
                raise

        return JSONResponse(
            content={
                "status": "success",
                "sids": message_sids,
                "message": "Messages sent successfully",
                "meta": meta,  # return original meta back to caller if needed
            },
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}", exc_info=True)
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Failed to send WhatsApp message: {str(e)}",
            },
            status_code=500,
        )
