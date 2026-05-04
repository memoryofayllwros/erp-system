import logging

import Levenshtein

from src.models.project_model import Project


def calculate_similarity(str1: str, str2: str) -> float:
    """
    Calculate similarity score between two strings using Levenshtein distance.
    Returns a score between 0 and 1, where 1 means identical strings.
    Handles special cases like substrings and common location suffixes.
    """
    if not str1 or not str2:
        return 0.0

    # Convert strings to lowercase for better matching
    str1 = str1.lower()
    str2 = str2.lower()

    # Check for exact match
    if str1 == str2:
        return 1.0

    # Check if one string is a substring of another
    if str1 in str2 or str2 in str1:
        # Calculate how much of the longer string is covered by the shorter one
        shorter = min(str1, str2, key=len)
        longer = max(str1, str2, key=len)
        substring_score = len(shorter) / len(longer)
        # Boost the score for substring matches
        return min(0.95, substring_score + 0.3)

    # Remove common location suffixes for comparison
    suffixes = ["碼頭", "倉庫", "大廈", "中心"]
    str1_clean = str1
    str2_clean = str2
    for suffix in suffixes:
        str1_clean = str1_clean.replace(suffix, "")
        str2_clean = str2_clean.replace(suffix, "")

    # Calculate Levenshtein distance on cleaned strings
    distance = Levenshtein.distance(str1_clean, str2_clean)

    # Calculate maximum possible distance
    max_len = max(len(str1_clean), len(str2_clean))
    if max_len == 0:
        return 1.0

    # Calculate similarity score (1 - normalized distance)
    similarity = 1 - (distance / max_len)

    # Boost score if original strings share common suffixes
    if any(suffix in str1 and suffix in str2 for suffix in suffixes):
        similarity = min(0.95, similarity + 0.2)

    return similarity
