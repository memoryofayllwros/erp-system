"""
The **project_code** of the project (required), usually consists of four letters and five-digit number, might end with 'NO', \
    for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
"""

import logging
from typing import Optional, Tuple
import difflib
from pydantic import BaseModel
from src.models.project_model import Project
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm
from src.nlp_helpers.levenshtein_distance import calculate_similarity

async def get_project_info_list():
    project_info_list = await Project.find(Project.deleted_at == None).to_list()
    project_info_list = [
        {
            "project_id": str(project.id),
            "project_code": str(project.project_code)
        }
        for project in project_info_list
    ]
    return project_info_list
    
class RAGProjectCode(BaseModel):
    project_code: str
    confidence: float = 0.0
    match_method: str = "none"

rag_project_code_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
            You are a helpful assistant that extracts project code from user input.
            You will be given a user input and a list of valid project codes. 
            Extract the project code from the user input that best matches one from the provided list.
            The project code is usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
            Pay attention to case sensitivity and common typing errors.
            Return the matched project code in JSON format.
            """
        ),
        ("human", "User input: {user_input}\n\nValid project codes:\n{project_codes_list}\n\nExtract the most matching project code from the user input."),
    ]
)

rag_project_code_chain = rag_project_code_template | gpt_4o_llm | JsonOutputParser(pydantic_object=RAGProjectCode)


def find_closest_project_code_fuzzy(user_input: str, project_codes: list[str]) -> Tuple[Optional[str], float]:
    """
    Find the closest matching project code using fuzzy string matching.
    Handles case-insensitive matching and common typing errors.
    
    Args:
        user_input: The project code input from user
        project_codes: List of valid project codes from database
        
    Returns:
        Tuple of (best_matching_code, confidence_score) or (None, 0.0) if no good match
    """
    if not user_input or not project_codes:
        return None, 0.0
    
    # Normalize input (uppercase for project codes)
    user_input_normalized = user_input.upper().strip()
    
    # Try exact match first
    if user_input_normalized in project_codes:
        return user_input_normalized, 1.0
    
    # Try case-insensitive match
    project_codes_lower = {code.upper(): code for code in project_codes}
    if user_input_normalized in project_codes_lower:
        return project_codes_lower[user_input_normalized], 0.95
    
    # Use difflib for fuzzy matching
    matches = difflib.get_close_matches(
        user_input_normalized, 
        project_codes, 
        n=1, 
        cutoff=0.6  # Require at least 60% similarity
    )
    
    if matches:
        best_match = matches[0]
        # Calculate similarity score
        similarity = difflib.SequenceMatcher(None, user_input_normalized, best_match).ratio()
        return best_match, similarity
    
    # Try using Levenshtein distance for better matching of similar strings
    best_match = None
    best_score = 0.0
    
    for code in project_codes:
        score = calculate_similarity(user_input_normalized, code.upper())
        if score > best_score:
            best_score = score
            best_match = code
    
    # Only return if we have a good enough match (>= 0.7)
    if best_match and best_score >= 0.7:
        return best_match, best_score
    
    return None, 0.0


async def find_closest_project_code_llm(user_input: str, project_codes: list[str]) -> Tuple[Optional[str], float]:
    """
    Find the closest matching project code using LLM semantic matching.
    
    Args:
        user_input: The project code input from user
        project_codes: List of valid project codes from database
        
    Returns:
        Tuple of (best_matching_code, confidence_score) or (None, 0.0) if no good match
    """
    if not user_input or not project_codes:
        return None, 0.0
    
    try:
        # Try exact match first
        if user_input.upper() in [code.upper() for code in project_codes]:
            return user_input.upper(), 1.0
        
        # Format project codes for LLM
        project_codes_str = "\n".join([f"- {code}" for code in project_codes])
        
        # Use LLM to find best match
        result = await rag_project_code_chain.ainvoke({
            "user_input": user_input,
            "project_codes_list": project_codes_str
        })
        
        matched_code = result.get("project_code")
        
        if matched_code and matched_code.upper() in [code.upper() for code in project_codes]:
            return matched_code, 0.9  # High confidence for LLM matches
        
        return None, 0.0
    
    except Exception as e:
        logging.error(f"Error in LLM project code matching: {str(e)}")
        return None, 0.0


async def find_closest_project_code_hybrid(user_input: str, project_codes: list[str], use_llm: bool = True) -> Tuple[Optional[str], float, str]:
    """
    Use hybrid approach: try fuzzy matching first, use LLM if needed.
    
    Args:
        user_input: The project code input from user
        project_codes: List of valid project codes from database
        use_llm: Whether to use LLM fallback
        
    Returns:
        Tuple of (best_matching_code, confidence_score, method_used)
    """
    if not user_input or not project_codes:
        return None, 0.0, "none"
    
    # Try fuzzy matching first (fast and effective for typos)
    fuzzy_code, fuzzy_score = find_closest_project_code_fuzzy(user_input, project_codes)
    
    # If fuzzy match is very confident, use it
    if fuzzy_code and fuzzy_score >= 0.9:
        logging.info(f"Using fuzzy match with confidence {fuzzy_score}: {fuzzy_code}")
        return fuzzy_code, fuzzy_score, "fuzzy"
    
    # If LLM is enabled and fuzzy confidence is low, try LLM
    if use_llm:
        llm_code, llm_score = await find_closest_project_code_llm(user_input, project_codes)
        
        if llm_score > fuzzy_score:
            logging.info(f"Using LLM match with confidence {llm_score}: {llm_code}")
            return llm_code, llm_score, "llm"
    
    # Return best result
    if fuzzy_code and fuzzy_score >= 0.7:
        logging.info(f"Using fuzzy match with confidence {fuzzy_score}: {fuzzy_code}")
        return fuzzy_code, fuzzy_score, "fuzzy"
    
    logging.warning(f"No good match found for project code: {user_input}")
    return None, 0.0, "none"


async def get_project_code_via_rag(user_input: str, use_llm: bool = True) -> dict:
    """
    Main function to get the most matching project code from user input using RAG.
    
    This function uses a hybrid approach with fuzzy string matching and LLM-based matching:
    1. First tries fuzzy matching (fast, handles typos)
    2. Falls back to LLM if needed (handles complex cases)
    
    Args:
        user_input: The project code input from user (might have errors or be lowercase)
                   Examples: "wlhk25003", "WLHK25003", "wlhk2500" (missing digit)
        use_llm: Whether to use LLM fallback for better matching (default: True)
        
    Returns:
        Dictionary with:
        - status: "success" or "error"
        - message: Descriptive message
        - matched_project_code: The best matching project code (or None)
        - confidence: Confidence score from 0.0 to 1.0
        - method: "fuzzy", "llm", or "none"
        
    Example usage:
        # Case 1: Lowercase input
        result = await get_project_code_via_rag("wlhk25003")
        # Returns: {"status": "success", "matched_project_code": "WLHK25003", "confidence": 1.0, "method": "fuzzy"}
        
        # Case 2: Typo in input
        result = await get_project_code_via_rag("wlhk2504")  # Missing last digit
        # Returns: {"status": "success", "matched_project_code": "WLHK25003", "confidence": 0.89, "method": "fuzzy"}
        
        # Case 3: No match found
        result = await get_project_code_via_rag("invalid123")
        # Returns: {"status": "error", "matched_project_code": None, "confidence": 0.0, "method": "none"}
    """
    try:
        # Get list of valid project codes from database
        project_info_list = await get_project_info_list()
        project_codes = [info["project_code"] for info in project_info_list]
        
        if not project_codes:
            return {
                "status": "error",
                "message": "No project codes found in database",
                "matched_project_code": None,
                "confidence": 0.0,
                "method": "none"
            }
        
        # Find best match using hybrid approach
        matched_code, confidence, method = await find_closest_project_code_hybrid(
            user_input, 
            project_codes, 
            use_llm=use_llm
        )
        
        if matched_code:
            return {
                "status": "success",
                "message": f"Matched project code: {matched_code}",
                "matched_project_code": matched_code,
                "confidence": confidence,
                "method": method
            }
        else:
            return {
                "status": "error",
                "message": f"No matching project code found for: {user_input}",
                "matched_project_code": None,
                "confidence": 0.0,
                "method": "none"
            }
    
    except Exception as e:
        logging.error(f"Error in get_project_code_via_rag: {str(e)}")
        return {
            "status": "error",
            "message": f"Error finding project code: {str(e)}",
            "matched_project_code": None,
            "confidence": 0.0,
            "method": "none"
        }


