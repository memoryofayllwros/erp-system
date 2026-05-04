import re
from typing import Tuple


def detect_language(text: str) -> str:
    """
    Detect if the text is primarily Chinese or English.
    Handles mixed content and provides more accurate detection.

    Args:
        text: Input text to analyze

    Returns:
        'zh' for Chinese, 'en' for English

    Note:
        - Considers both traditional and simplified Chinese characters
        - Handles mixed content by calculating character ratios
        - Ignores numbers and punctuation in the analysis
    """
    if not text or not isinstance(text, str):
        return "en"

    # Remove numbers and common punctuation
    text = re.sub(r'[\d\s\.,!?;:"\'\(\)\[\]\{\}]', "", text)

    # Count character types
    chinese_chars = len(
        re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text)
    )  # Include extended ranges
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    total_chars = len(text)

    if total_chars == 0:
        return "en"

    # Calculate ratios
    chinese_ratio = chinese_chars / total_chars
    english_ratio = english_chars / total_chars

    # If text has significant Chinese content (>20%), classify as Chinese
    if chinese_ratio > 0.2:
        return "zh"
    # If text has more English characters than other types, classify as English
    elif english_ratio > 0.5:
        return "en"
    # Default to English for ambiguous cases
    return "en"


def get_language_stats(text: str) -> Tuple[float, float]:
    """
    Get detailed statistics about language composition of text.

    Args:
        text: Input text to analyze

    Returns:
        Tuple of (chinese_ratio, english_ratio)
    """
    if not text or not isinstance(text, str):
        return (0.0, 0.0)

    # Remove numbers and common punctuation
    text = re.sub(r'[\d\s\.,!?;:"\'\(\)\[\]\{\}]', "", text)

    # Count character types
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    total_chars = len(text) if len(text) > 0 else 1

    return (chinese_chars / total_chars, english_chars / total_chars)
