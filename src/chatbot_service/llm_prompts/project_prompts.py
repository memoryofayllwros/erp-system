import json
import logging
from itertools import chain
from typing import Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, field_validator

from src.chatbot_service.chatbot_helpers.setup_llm import (gpt_4o_llm,
                                                           gpt_mini_llm)
from src.chatbot_service.llm_prompts.llm_prompt_helpers.rag_project_code import get_project_code_via_rag

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

load_dotenv()


# ==================== Data Models ====================


class ExtractProjectLocation(BaseModel):
    """Model for detailed project location information."""

    region: str = Field(description="地區/市 (e.g., 香港, 新界, 九龍)")
    district: str = Field(description="區份 (e.g., 北區, 荃灣, 中西區)")
    street: str = Field(description="街道名稱")
    building: Optional[str] = Field(default=None, description="建築物/號碼")


class ExtractProjectInfo(BaseModel):
    """Model for basic project information."""

    project_title: str
    client_name: str
    project_location: str


class AddProjectInfo(BaseModel):
    """Model for complete project information with structured location."""

    project_title: str
    client_name: str
    project_location: ExtractProjectLocation


# ==================== Project Info Extraction Chain ====================

add_project_info_parser = JsonOutputParser(pydantic_object=ExtractProjectInfo)
add_project_info_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是一個訓練有素的助理，負責從用戶輸入的中文訊息中提取並結構化項目信息。你的任務是**準確地擷取並格式化項目資料**，特別注意項目編號和其他補充資料。輸出必須為有效的 JSON 格式，並只包含指定欄位。
            You are a highly skilled assistant responsible for extracting and structuring **project information** from user input in Chinese.
            Your main task is to **accurately extract and format project details** with special attention to project number and additional information.

### 📌 **需要擷取的項目欄位**

1. **項目名稱 project_title** REQUIRED✅
   - 項目的名稱，例如: 
     - 聯合醫院
     - 粉嶺馬會道資助出售房屋(房協)
     - 香港西營盤皇后大道西/賢居里住宅項目(URA)

2. **主承建商 client_name** REQUIRED✅
   - 必須為一個主承建商，例如: 「中國建築」、「中國鐵建」、「中國交通建設」
   - 例子: 
     - 「中國建築」、「中國鐵建」、「中國交通建設」, etc.

3. **項目地址 project_location** REQUIRED✅
   - 必須為一個項目地址，例如: 「港島」、「九龍」、「新界」
   - 例子: 
     - 「新界錦田錦上路 LOT 1415 DD114 地下」
     -  'Hong Kong, North Point, 651 King's Road, Unit 02, 17/F' 
---

### 🧠 **指引與限制**

- **不要**翻譯、創造或猜測資料。
- **不要**輸出未指定的欄位。
- 將項目名稱和主承建商和項目地址作為必要欄位。
- 其他欄位為選填，但必須準確提取。
- 如果有必要欄位缺失，請回傳錯誤 JSON，或提示用戶提供缺失資料。

---

### ✨ **輸出格式（請嚴格遵守）**

只允許以下格式，**請勿加入解釋、說明或額外訊息**: 
{{"project_title": "<項目名稱 required>", "client_name": "<主承建商 required>", "project_location": "<項目地址 required>"}}""",
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=add_project_info_parser.get_format_instructions())

project_info_chain = add_project_info_template | gpt_4o_llm | add_project_info_parser


# ==================== Project Location Extraction Chain ====================

project_location_parser = JsonOutputParser(pydantic_object=ExtractProjectLocation)
project_location_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是一個訓練有素的地址解析助理，負責從項目地址中提取並結構化地點信息。
你的任務是**準確地分解地址**成為區域、地區、街道和建築物等組成部分。

### 📌 **需要擷取的地點欄位**

1. **地區 region** REQUIRED✅
   - 香港的主要地區，例如: 「港島」、「九龍」、「新界」
   - 也可以是更具體的位置，如「香港」、「九龍西」等

2. **區份 district** REQUIRED✅
   - 香港的區份，例如: 「中西區」、「灣仔」、「東區」、「南區」、「油尖旺」、「深水埗」、「黃大仙」、「觀塘」、「荃灣」、「葵青」、「北區」、「大埔」、「沙田」、「屯門」、「元朗」、「離島」等

3. **街道 street** REQUIRED✅
   - 街道的名稱，例如: 「皇后大道西」、「錦上路」、「King's Road」

4. **建築物 building** OPTIONAL
   - 建築物號碼、名稱或單位，例如: 「LOT 1415 DD114 地下」、「Unit 02, 17/F」、「651號」

---

### 🧠 **指引**

- **不要**翻譯或創造資料，只提取實際提供的信息。
- 如果某些字段不在地址中，請設置為 null。
- 準確識別地區和區份。
- 保留原始格式（中文或英文）。

---

### ✨ **輸出格式**

只允許以下 JSON 格式，**請勿加入解釋**: 
{{"region": "<地區 required>", "district": "<區份 required>", "street": "<街道 required>", "building": "<建築物 optional or null>"}}""",
        ),
        ("human", "{location_text}"),
    ]
).partial(format_instructions=project_location_parser.get_format_instructions())

project_location_chain = (
    project_location_template | gpt_4o_llm | project_location_parser
)


# ==================== Extraction Functions ====================


def add_project_response(body):
    """
    Extract basic project information from user input.

    Args:
        body (str or list): User input containing project information

    Returns:
        dict: {
            "success": bool,
            "data": ExtractProjectInfo details or None,
            "error": str or None
        }
    """
    try:
        if isinstance(body, list):
            body = " ".join(body)

        parse_project_info = project_info_chain.invoke({"messages": body})

        if isinstance(parse_project_info, ExtractProjectInfo):
            result = parse_project_info.model_dump()
        elif isinstance(parse_project_info, dict):
            result = parse_project_info
        else:
            return {
                "success": False,
                "data": None,
                "error": "Unexpected response format.",
            }

        # Validate required fields
        required_fields = ["project_title", "client_name", "project_location"]
        missing_fields = [field for field in required_fields if not result.get(field)]

        if missing_fields:
            return {
                "success": False,
                "data": result,
                "error": f"Missing required fields: {', '.join(missing_fields)}",
            }

        final_message = {"success": True, "data": result}
        logger.info(f"Project info extracted successfully: {final_message}")
        return final_message

    except Exception as e:
        logger.error(f"Error extracting project info: {str(e)}", exc_info=True)
        return {"success": False, "data": None, "error": str(e)}


def extract_project_location_details(location_text):
    """
    Extract detailed location information from a project location string.

    Args:
        location_text (str or list): The project location text to parse

    Returns:
        dict: {
            "success": bool,
            "data": ExtractProjectLocation details or None,
            "error": str or None
        }
    """
    try:
        if isinstance(location_text, list):
            location_text = " ".join(location_text)

        if not location_text or not location_text.strip():
            return {
                "success": False,
                "data": None,
                "error": "Location text cannot be empty",
            }

        parsed_location = project_location_chain.invoke(
            {"location_text": location_text}
        )

        if isinstance(parsed_location, ExtractProjectLocation):
            result = parsed_location.model_dump()
        elif isinstance(parsed_location, dict):
            result = parsed_location
        else:
            return {
                "success": False,
                "data": None,
                "error": "Unexpected response format from location parser",
            }

        # Validate required fields
        required_fields = ["region", "district", "street"]
        missing_fields = [field for field in required_fields if not result.get(field)]

        if missing_fields:
            return {
                "success": False,
                "data": result,
                "error": f"Missing required fields: {', '.join(missing_fields)}",
            }

        final_message = {"success": True, "data": result}
        logger.info(f"Project location details extracted: {final_message}")
        return final_message

    except Exception as e:
        logger.error(
            f"Error extracting project location details: {str(e)}", exc_info=True
        )
        return {"success": False, "data": None, "error": str(e)}


def extract_complete_project_info(user_input):
    """
    Complete pipeline to extract and structure full project information.
    Combines basic project info extraction with detailed location parsing.

    Args:
        user_input (str or list): User input containing project information

    Returns:
        dict: {
            "success": bool,
            "data": {
                "project_title": str,
                "client_name": str,
                "project_location": {
                    "region": str,
                    "district": str,
                    "street": str,
                    "building": str or None
                }
            },
            "error": str or None
        }
    """
    try:
        # Step 1: Extract basic project info
        basic_info = add_project_response(user_input)

        if not basic_info["success"]:
            return basic_info

        project_data = basic_info["data"]

        # Step 2: Extract detailed location information
        location_details = extract_project_location_details(
            project_data["project_location"]
        )

        if location_details["success"]:
            # Replace string location with structured location object
            project_data["project_location"] = location_details["data"]
            logger.info(f"Complete project info extracted: {project_data}")
        else:
            logger.warning(
                f"Failed to extract location details: {location_details['error']}"
            )
            # Keep original location string if detailed extraction fails
            return {
                "success": False,
                "data": project_data,
                "error": f"Location parsing failed: {location_details['error']}",
            }

        return {"success": True, "data": project_data}

    except Exception as e:
        logger.error(
            f"Error in complete project extraction pipeline: {str(e)}", exc_info=True
        )
        return {"success": False, "data": None, "error": str(e)}



#=================== Add Project GPS Info ====================

class AddProjectGpsInfo(BaseModel):
    project_code: str
    location_name: str


add_project_gps_parser = JsonOutputParser(pydantic_object=AddProjectGpsInfo)
add_project_gps_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是一個訓練有素的助理，負責從用戶輸入的中文訊息中提取並結構化項目信息，特別是與GPS位置相關的資料。你的任務是**準確地擷取並格式化項目編號和位置名稱**。輸出必須為有效的 JSON 格式，並只包含指定欄位。
            You are a highly skilled assistant responsible for extracting and structuring **project information related to GPS locations** from user input in Chinese.
            Your main task is to **accurately extract and format project_code and location_name**.

### 📌 **需要擷取的項目欄位**

1. **項目編號 project_code** ✅
   - Usually consists of four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WLSS25003NO' etc.
   - 例子: 
     - 「WLHK25003」、「WCGEO25002」、「WLSS24007NO」, etc.
   - 可能出現在以下格式中: 「項目編號WLHK25003」、「項目編號WCGEO25002」等

2. **位置名稱 location_name** ✅
   - 必須為一個地點名稱，例如: 「環球大廈南出口」、「中環皇后大道中123號」、「銅鑼灣時代廣場」
   - 例子: 
     - 「環球大廈南出口」、「中環皇后大道中123號」、「銅鑼灣時代廣場」, etc.
   - 可能出現在以下格式中: 「位置名稱: 中環皇后大道中123號」、「地點: 銅鑼灣時代廣場」等

---

### 🧠 **指引與限制**

- **不要**翻譯、創造或猜測資料。
- **不要**輸出未指定的欄位。
- 如果有必要欄位缺失，請回傳錯誤 JSON，或提示用戶提供缺失資料。
- 請特別注意用戶可能同時提供了位置座標和項目資料，需要準確地從中提取項目編號和位置名稱。
- 用戶可能先提供位置座標，然後再提供項目編號和位置名稱，需要從後續訊息中提取。

---

### ✨ **輸出格式（請嚴格遵守）**

只允許以下格式，**請勿加入解釋、說明或額外訊息**: 
{{"project_code": "<project code>", "location_name": "<location name>"}}""",
        ),
        ("human", "{messages}"),
    ]
).partial(format_instructions=add_project_gps_parser.get_format_instructions())

add_project_gps_chain = add_project_gps_template | gpt_4o_llm | add_project_gps_parser


async def add_project_gps_response(body):
    """
    Extract project number and location name for GPS location data and validate project code using RAG.
    This function is designed to handle messages that might include GPS coordinates.

    Args:
        body (str or list): The message body to extract information from

    Returns:
        dict: Extracted project number and location name with validated project_code
    """
    try:
        if isinstance(body, list):
            body = " ".join(body)

        logging.info(f"Extracting GPS project info from: {body}")
        add_project_gps_info = add_project_gps_chain.invoke({"messages": body})
        logging.info(f"Extracted GPS project info: {add_project_gps_info}")

        # Parse string result as JSON if needed
        if not isinstance(add_project_gps_info, dict):
            if (
                isinstance(add_project_gps_info, str)
                and "{" in add_project_gps_info
                and "}" in add_project_gps_info
            ):
                json_start = add_project_gps_info.index("{")
                json_end = add_project_gps_info.rindex("}") + 1
                extracted_json = add_project_gps_info[json_start:json_end]
                try:
                    parsed_json = json.loads(extracted_json)
                    logging.info(f"Parsed JSON from string: {parsed_json}")
                    add_project_gps_info = parsed_json
                except json.JSONDecodeError as e:
                    logging.error(f"Error decoding JSON: {str(e)}")
                    return {"error": f"Error decoding JSON: {str(e)}"}

        if isinstance(add_project_gps_info, dict):
            # Validate the extracted data
            if (
                "project_code" in add_project_gps_info
                and add_project_gps_info["project_code"]
            ):
                original_project_code = add_project_gps_info["project_code"]
                location_name = add_project_gps_info.get("location_name")
                
                # Log successful extraction
                logging.info(
                    f"Successfully extracted project_code: {original_project_code}"
                )
                
                # Step 2: Validate and correct project_code using RAG
                rag_result = await get_project_code_via_rag(original_project_code, use_llm=True)
                
                if rag_result["status"] == "success":
                    validated_project_code = rag_result["matched_project_code"]
                    confidence = rag_result["confidence"]
                    method = rag_result["method"]
                    
                    logger.info(
                        f"RAG validation successful for add_project_gps: {original_project_code} -> {validated_project_code} "
                        f"(confidence: {confidence}, method: {method})"
                    )
                    
                    # Return validated project code
                    return {
                        "project_code": validated_project_code,
                        "location_name": location_name,
                    }
                else:
                    # RAG validation failed - check if original extraction was close enough
                    logger.warning(
                        f"RAG validation failed for '{original_project_code}': {rag_result['message']}"
                    )
                    
                    # If original extraction looks valid (has proper format), use it with warning
                    # Project codes are typically 4 letters + 5 digits, might end with 'NO'
                    if original_project_code and len(original_project_code) >= 9:
                        logger.info(
                            f"Using original extracted project_code '{original_project_code}' "
                            "despite RAG validation failure"
                        )
                        return {
                            "project_code": original_project_code.upper(),
                            "location_name": location_name,
                            "warning": rag_result["message"],
                        }
                    else:
                        return {
                            "error": (
                                f"無法驗證工程編號 '{original_project_code}'. "
                                f"{rag_result['message']}"
                            )
                        }
            else:
                logging.warning("Missing project_code in extracted data")
                return {"error": "Missing project_code in extracted data"}

        # Return the original result if we couldn't parse it
        return add_project_gps_info

    except Exception as e:
        logging.error(f"Error in add_project_gps_response: {str(e)}", exc_info=True)
        return {"error": str(e)}



#=================== Read Specific Project Info ====================

class ReadSpecificProjectInfo(BaseModel):
    project_code: str

read_specific_project_parser = JsonOutputParser(pydantic_object=ReadSpecificProjectInfo)

read_specific_project_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a highly skilled assistant responsible for extracting project information from user input.
Your task is to accurately identify the project_code when a user wants to read specific project.

### 📌 **Fields to Extract**
1. **project_code** [REQUIRED]
   - The project_code to read specific project for
   - Example: "WLHK25003", "WCGEO25002"
   - Extract from phrases like "project [number]", "for project [number]", "read specific project for [number]"

### 🧠 **Strict Processing Rules**
- Only project_code is required
- project_code should be a four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO' etc.
- Return error if project_code is missing

### 🔍 **Pattern Recognition Examples**
Input: "Read specific project for WLHK25003"
Output:
{{
    "project_code": "WLHK25003"
}}

Input: "project WCGEO25002 details"
Output:
{{
    "project_code": "WCGEO25002"
}}

Input: "project info of WCGEO25002"
Output:
{{
    "project_code": "WCGEO25002"
}}

### ✨ **Output Format**
Return ONLY this JSON format (no explanations or additional text):
{{
    "project_code": "<project code>"
}}""",
        ),
        ("human", "{messages}"),
    ]
)

read_specific_project_chain = (
    read_specific_project_template | gpt_4o_llm | read_specific_project_parser
)


async def read_specific_project_response(body: str) -> dict:
    """
    Extract project_code for reading specific project and validate/correct it using RAG.
    
    This function:
    1. Extracts project_code from user input using LLM
    2. Validates and corrects the extracted project_code against actual project codes in database
    3. Returns the validated/corrected project_code with confidence information
    
    Args:
        body: User input string containing project code request
        
    Returns:
        dict: {
            "success": bool,
            "data": {
                "project_code": str,  # Validated/corrected project code
                "confidence": float,  # Confidence score (0.0 to 1.0)
                "method": str,  # Matching method used: "exact", "fuzzy", "llm", or "none"
                "original_extracted": str  # Original project code extracted by LLM
            } or None,
            "error": str or None
        }
    """
    try:
        # Step 1: Extract project_code from user input using LLM
        parsed_info = read_specific_project_chain.invoke({"messages": body})
        
        if not parsed_info or not parsed_info.get("project_code"):
            return {
                "success": False,
                "data": None,
                "error": "Failed to extract project_code from user input",
            }
        
        original_project_code = parsed_info.get("project_code")
        logger.info(f"Extracted project_code from input: {original_project_code}")
        
        # Step 2: Validate and correct using RAG
        rag_result = await get_project_code_via_rag(original_project_code, use_llm=True)
        
        if rag_result["status"] == "success":
            validated_project_code = rag_result["matched_project_code"]
            confidence = rag_result["confidence"]
            method = rag_result["method"]
            
            logger.info(
                f"RAG validation successful: {original_project_code} -> {validated_project_code} "
                f"(confidence: {confidence}, method: {method})"
            )
            
            # Return validated project code with metadata
            return {
                "success": True,
                "data": {
                    "project_code": validated_project_code,
                    "confidence": confidence,
                    "method": method,
                    "original_extracted": original_project_code,
                },
            }
        else:
            # RAG validation failed - check if original extraction was close enough
            logger.warning(
                f"RAG validation failed for '{original_project_code}': {rag_result['message']}"
            )
            
            # If original extraction looks valid (has proper format), use it with low confidence
            # Project codes are typically 4 letters + 5 digits, might end with 'NO'
            if original_project_code and len(original_project_code) >= 9:
                logger.info(
                    f"Using original extracted project_code '{original_project_code}' "
                    "despite RAG validation failure"
                )
                return {
                    "success": True,
                    "data": {
                        "project_code": original_project_code.upper(),
                        "confidence": 0.5,  # Low confidence since not validated
                        "method": "llm_extraction_only",
                        "original_extracted": original_project_code,
                        "warning": rag_result["message"],
                    },
                }
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"Failed to validate project_code '{original_project_code}'. "
                        f"{rag_result['message']}"
                    ),
                }
    
    except Exception as e:
        logger.error(f"Error in read_specific_project_response: {str(e)}", exc_info=True)
        return {"success": False, "data": None, "error": str(e)}


#=================== Remove Project GPS Location Info ====================

class RemoveProjectGpsLocationInfo(BaseModel):
    project_code: str
    location_name: str

remove_project_gps_location_parser = JsonOutputParser(
    pydantic_object=RemoveProjectGpsLocationInfo
)

remove_project_gps_location_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a highly skilled assistant responsible for extracting project information from user input.
Your task is to accurately identify the project_code and location_name when a user wants to remove a GPS location for a project.

### 📌 **Fields to Extract**
1. **項目編號 project_code** [REQUIRED] ✅
   - The project_code to remove a GPS location for
   - Example: "WLHK25003", "WCGEO25002"
   - Extract from phrases like "remove GPS location for project [number]", "remove GPS location for [number]", "remove GPS location for [number]"

### 🧠 **Strict Processing Rules**
- Only project_code and location_name are required
- project_code should be a four letters and five-digit number, might end with 'NO', for example, 'WLHK25003', 'WCGEO25002', 'WCGE25003NO', etc.
- location_name should be a valid location name
- Return error if project_code or location_name is missing

### 🔍 **Pattern Recognition Examples**
Input: "remove GPS location for project WLHK25003"
Output:
{{
    "project_code": "WLHK25003",
    "location_name": "環球大廈南出口"
}}

Input: "remove GPS location for WCGEO25002"
Output:
{{
    "project_code": "WCGEO25002",
    "location_name": "中環皇后大道中123號"
}})].""",
        ),
        ("human", "{messages}"),
    ]
).partial(
    format_instructions=remove_project_gps_location_parser.get_format_instructions()
)

remove_project_gps_location_chain = (
    remove_project_gps_location_template
    | gpt_4o_llm
    | remove_project_gps_location_parser
)


async def remove_project_gps_location_response(body):
    """
    Extract project_code and location_name for removing GPS location and validate project code using RAG.
    
    Args:
        body: User input string containing project code and location name
        
    Returns:
        dict: {
            "success": bool,
            "data": {
                "project_code": str,  # Validated/corrected project code
                "location_name": str,
                "confidence": float,  # Confidence score (0.0 to 1.0)
                "method": str,  # Matching method used
                "original_extracted": str  # Original project code extracted by LLM
            } or None,
            "error": str or None
        }
    """
    try:
        # Step 1: Extract project_code and location_name from user input using LLM
        parsed_info = remove_project_gps_location_chain.invoke({"messages": body})
        
        if not parsed_info or not parsed_info.get("project_code"):
            return {
                "success": False,
                "data": None,
                "error": "Failed to extract project_code from user input",
            }
        
        original_project_code = parsed_info.get("project_code")
        location_name = parsed_info.get("location_name")
        
        logger.info(f"Extracted project_code from input: {original_project_code}")
        
        # Step 2: Validate and correct using RAG
        rag_result = await get_project_code_via_rag(original_project_code, use_llm=True)
        
        if rag_result["status"] == "success":
            validated_project_code = rag_result["matched_project_code"]
            confidence = rag_result["confidence"]
            method = rag_result["method"]
            
            logger.info(
                f"RAG validation successful for remove_project_gps: {original_project_code} -> {validated_project_code} "
                f"(confidence: {confidence}, method: {method})"
            )
            
            # Return validated project code with metadata
            return {
                "success": True,
                "data": {
                    "project_code": validated_project_code,
                    "location_name": location_name,
                    "confidence": confidence,
                    "method": method,
                    "original_extracted": original_project_code,
                },
            }
        else:
            # RAG validation failed - check if original extraction was close enough
            logger.warning(
                f"RAG validation failed for '{original_project_code}': {rag_result['message']}"
            )
            
            # If original extraction looks valid (has proper format), use it with low confidence
            # Project codes are typically 4 letters + 5 digits, might end with 'NO'
            if original_project_code and len(original_project_code) >= 9:
                logger.info(
                    f"Using original extracted project_code '{original_project_code}' "
                    "despite RAG validation failure"
                )
                return {
                    "success": True,
                    "data": {
                        "project_code": original_project_code.upper(),
                        "location_name": location_name,
                        "confidence": 0.5,  # Low confidence since not validated
                        "method": "llm_extraction_only",
                        "original_extracted": original_project_code,
                        "warning": rag_result["message"],
                    },
                }
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"無法驗證工程編號 '{original_project_code}'. "
                        f"{rag_result['message']}"
                    ),
                }
    
    except Exception as e:
        logger.error(f"Error in remove_project_gps_location_response: {str(e)}", exc_info=True)
        return {"success": False, "data": None, "error": str(e)}
