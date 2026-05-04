import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Union

from datetime import date, datetime

from src.utils.language_detection import detect_language

from src.utils.datetime_standarization_helpers import HK_TZ

def get_month_range_from_str(month_str: str) -> tuple[datetime, datetime]:
    """
    根據 'YYYY-MM' 格式字串，返回該月的起始與結束日期範圍（end exclusive）。

    例子:
    '2025-01' -> (2025-01-01 00:00:00, 2025-02-01 00:00:00)
    """
    try:
        start = datetime.strptime(month_str, "%Y-%m")
    except ValueError as e:
        raise ValueError(
            f"Invalid month string format: {month_str}. Expected format 'YYYY-MM'."
        ) from e

    # Get first day of the next month
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)

    return start, end


def format_name(name: str) -> str:
    """
    Format a name according to language and name conventions.

    Args:
        name: Input name to format

    Returns:
        Formatted name string

    Features:
        - Handles English names with proper title case
        - Preserves Chinese names without modification
        - Handles mixed language names appropriately
        - Removes extra whitespace and normalizes spacing
        - Preserves hyphenated names
    """
    if not name or not isinstance(name, str):
        return name

    # Clean whitespace
    name = " ".join(name.split())

    # Detect language
    lang = detect_language(name)

    if lang == "en":
        # Handle hyphenated names
        parts = name.split("-")
        formatted_parts = []
        for part in parts:
            # Title case each part, preserving spacing
            words = part.strip().split()
            formatted_words = []
            for word in words:
                # Special case for McName or MacName
                if word.lower().startswith(("mc", "mac")) and len(word) > 3:
                    formatted_words.append(
                        word[:2].title() + word[2:3].upper() + word[3:].lower()
                    )
                else:
                    formatted_words.append(word.title())
            formatted_parts.append(" ".join(formatted_words))
        return "-".join(formatted_parts)

    # Return Chinese names unchanged
    return name


def format_company_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return name

    # Clean whitespace
    name = " ".join(name.split())

    # Detect language
    lang = detect_language(name)

    if lang == "en":
        # Handle common company suffixes
        suffixes = [
            "ltd",
            "limited",
            "inc",
            "incorporated",
            "llc",
            "corp",
            "corporation",
        ]
        words = name.split()
        formatted_words = []

        for i, word in enumerate(words):
            word_lower = word.lower()
            # Keep common suffixes uppercase
            if word_lower in suffixes and i == len(words) - 1:
                formatted_words.append(word_lower.upper())
            # Handle special cases like "Co." or "Ltd."
            elif word_lower.rstrip(".") in ["co", "ltd"]:
                formatted_words.append(
                    word_lower.upper() + ("." if word.endswith(".") else "")
                )
            else:
                formatted_words.append(word.title())

        return " ".join(formatted_words)

    # Return Chinese names unchanged
    return name


shippment_name = "運輸費"


def safe_decimal(value: str):
    try:
        # Remove currency symbols and commas
        cleaned = re.sub(r"[^\d.]", "", value)
        return Decimal(cleaned)
    except (InvalidOperation, TypeError) as e:
        logging.error(f"Decimal conversion failed for value '{value}': {str(e)}")
        return None


def format_price(price: Union[str, float, int]) -> str:
    return "{:.2f}".format(Decimal(price))


# List of allowed country codes as strings (sorted by length desc to match longest first)
COMMON_COUNTRY_CODES = [
    "852",
    "853",
    "86",
    "1",
    "60",
    "65",
    "66",
    "67",
    "68",
    "69",
    "7",
    "8",
    "9",
]


def normalize_mobile_from_whatsapp(mobile: str):
    # Remove 'whatsapp:' or other prefixes
    if ":" in mobile:
        _, mobile = mobile.split(":", 1)

    # Remove '+' and non-digit characters
    mobile_digits = "".join(filter(str.isdigit, mobile))

    # Try to match the country code from known list
    for code in sorted(COMMON_COUNTRY_CODES, key=lambda x: -len(x)):
        if mobile_digits.startswith(code):
            country_code = code
            mobile_digits = mobile_digits[len(code) :]
            result = {"country_code": country_code, "mobile_digits": mobile_digits}
            return result

    # If no match found, use default country code
    # Using 852 (Hong Kong) as default
    country_code = "852"
    mobile_info = {"country_code": country_code, "mobile_digits": mobile_digits}
    return mobile_info


async def validate_mobile_from_whatsapp(mobile: str):
    from src.models.user_model import User

    result = normalize_mobile_from_whatsapp(mobile)
    whatsapp_mobile = result["mobile_digits"]
    whatsapp_country_code = result["country_code"]

    try:
        # Convert single mobile string to list for compatibility with User model
        mobile_list = [whatsapp_mobile]
        sender_info = await User.find_one(
            User.mobile == whatsapp_mobile,
            User.country_code == whatsapp_country_code,
            User.deleted_at == None,
        )
        logging.info(f"Sender info from validate_mobile_from_whatsapp: {sender_info}")
        return sender_info  # Simply return None if no user found
    except Exception as e:
        logging.error(f"Error finding user with mobile {whatsapp_mobile} and country code {whatsapp_country_code}: {e}")
        # Try to find the user with just the mobile number as a fallback
        try:
            mobile_list = [whatsapp_mobile]
            sender_info = await User.find_one(
                User.mobile == whatsapp_mobile,
                User.deleted_at == None,
            )
            logging.info(f"Found user with just mobile number: {sender_info}")
            return sender_info
        except Exception as e2:
            logging.error(f"Error in fallback user search: {e2}")
            return None


def standardize_timestamp(timestamp: datetime) -> datetime:

    if not isinstance(timestamp, datetime):
        raise ValueError("timestamp must be a datetime object")

    try:
        # Handle naive timestamps - assume they are in HK timezone
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone(HK_TZ)

        return timestamp

    except Exception as e:
        raise ValueError(f"Invalid timezone or timestamp: {e}") from e


async def parse_date(date_str: str) -> Optional[date]:
    """
    Parses a date string into a `date` object.
    Supports multiple date formats commonly used (e.g. 18/11/2023, 18-11-23).
    Returns None if parsing fails.
    """

    def clean_date_string(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        return raw.strip().rstrip(":").rstrip(".")

    cleaned_str = clean_date_string(date_str)
    if not cleaned_str:
        return None

    date_formats = [
        "%d/%m/%Y",  # e.g. 18/11/2023
        "%d-%m-%Y",  # e.g. 18-11-2023
        "%d/%m/%y",  # e.g. 18/11/23
        "%d-%m-%y",  # e.g. 18-11-23
        "%Y-%m-%d",  # e.g. 2023-11-18 (ISO)
    ]

    for fmt in date_formats:
        try:
            return datetime.strptime(cleaned_str, fmt).date()
        except ValueError:
            continue

    logging.warning(
        f"❌ Failed to parse date: original='{date_str}' cleaned='{cleaned_str}'"
    )
    return None




def convert_to_30_hour_clock_format(timestamp: datetime) -> datetime:

    """Convert time to 30 hour clock format"""

    timestamp = timestamp.replace(hour=timestamp.hour + 24)
    logging.info(f"Converted to 30 hour clock format: {timestamp}")

    return timestamp