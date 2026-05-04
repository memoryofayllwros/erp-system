# state definition of my graph

from enum import Enum
from typing import Annotated, Dict, List, Optional, TypedDict

from src.chatbot_service.langgraph.message_history import LimitedHistory


class WorkflowStatus_Enum(str, Enum):
    COLLECTING_IMAGES = "collecting_images"
    AWAIT_INTENT = "await_intent"
    AWAIT_DOCUMENT_VALIDATION = "await_document_validation"
    AWAIT_FIELD = "await_field"
    FIELD_VALIDATED = "field_validated"
    SLOT_FILLED = "slot_filled"
    ENTITY_VALIDATED = "entity_validated"
    CRUD_EXECUTED = "crud_operations_executed"
    SUCCESS = "success"
    TEMP_END = "temp_end"  # for temp end of workflow
    AWAIT_HUMAN_CONFIRMATION = "await_human_confirmation"


WorkflowStatus = {
    "temp_end",
    "await_intent",
    "await_document_validation",
    "await_field",
    "field_validated",
    "slot_filled",
    "entity_validated",
    "success",
    "collecting_images",
    "crud_operations_executed",
}


def merge_status(_, new_values):
    # Flatten accidentally split strings
    if all(isinstance(v, str) and len(v) == 1 for v in new_values):
        combined = "".join(new_values)
        return combined

    last = new_values[-1]
    if isinstance(last, str):
        return last
    return str(last)  # Fallback to string representation


def merge_media_urls(_, new_values):
    """
    Custom merge function for media_urls that deduplicates URLs instead of concatenating them.
    This prevents the accumulation of duplicate URLs across different nodes.
    """
    if not new_values:
        return []

    # Flatten all URL lists
    all_urls = []
    for value in new_values:
        if isinstance(value, list):
            all_urls.extend(value)
        elif value:  # Handle single URL strings
            all_urls.append(value)

    # Deduplicate URLs
    unique_urls = []
    seen_urls = set()

    for url in all_urls:
        if url and url.strip():  # Check for non-empty, non-whitespace URLs
            if url not in seen_urls:
                unique_urls.append(url)
                seen_urls.add(url)

    return unique_urls


# Instantiate with a limit of 10 messages
limited_history = LimitedHistory(max_messages=2)


class WorkflowState(TypedDict):
    messages: Annotated[list, limited_history]
    current_intent: str
    extracted_fields: dict
    validated: bool
    status: Annotated[str, merge_status]
    action_result: str
    error: bool
    media_urls: Annotated[
        List[str], merge_media_urls
    ]  # Support for multiple images with deduplication

    image_collection_active: Optional[
        bool
    ]  # true (active) if medial_urls is not empty, false (inactive) if medial_urls is empty
    image_collection_processed: Optional[
        bool
    ]  # true (processed) if image_collection_active is true and all images in medial_urls have been collected (collected_image_count is equal to image_count)
    image_count: Optional[int]  # number of images in medial_urls
    collected_image_count: Optional[
        int
    ]  # number of images in medial_urls that have been collected
    collection_timeout_seconds: Optional[
        float
    ]  # timeout in seconds, 30 seconds, for the image collection
    collection_timeout_passed: Optional[
        bool
    ]  # true (passed) if collection_timeout_seconds, 30 seconds, has passed since the last image was collected.
    original_body: Optional[
        str
    ]  # original message body with important information like project number
    done_command_received: Optional[
        bool
    ]  # true (received) if the user has sent the 'done' command

    human_confirmation_received: Optional[
        bool
    ]  # true (received) if the user has sent the 'yes' or 'no' command
