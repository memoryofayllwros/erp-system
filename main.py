# Version 0.1
# Authors: Virpluz Ltd. Jing Wang
# Date: 25-Oct-2025

#---------------------------README -------------------------------
# Main application entry point for wls Assistant API
# Sets up FastAPI app with Temporal and Redis integrations
# Handles incoming webhooks from Twilio WhatsApp
# Manages conversation state and media collections
# Integrates with AI workflows for message processing

# Main Flow:
# WhatsApp Message → Webhook → State Management → AI Workflow → Response → State Cleanup

# Scenario 1: Worker Registration
"""
FLOW: User Registration with ID Card
1. User: "我想註冊" + ID card image
2. System: Extract text from ID card (OCR)
3. System: Validate required fields
4. System: Create user account
5. System: Send confirmation
6. State: Cleanup (conversation complete)
"""

# Message 1: Intent classification → "registration"
# Message 2: Entity extraction → OCR processing
# Message 3: Validation → Check required fields
# Message 4: Database operation → Create user
# Message 5: Response → Confirmation message

#Scenario 2: Multi-Image Worker Card Upload
"""
FLOW: Multiple Worker Cards Processing
1. User: "add cards project 25001" + first image
2. System: Start image collection mode
3. User: Sends more images (2nd, 3rd, 4th...)
4. System: Collects all images in Redis
5. User: "done" or timeout
6. System: Process all cards with OCR
7. System: Create worker records
8. State: Cleanup after completion
"""

# State preservation is critical here
# Each image message preserves the collection state
# Only processes when "done" or timeout occurs

#Scenario 3: GPS Check-in
"""
FLOW: GPS-based Attendance Check-in
1. User: "check in" + GPS coordinates
2. System: Classify intent → "check_in_via_gps"  
3. System: Generate check-in link with GPS
4. System: Send link to user
5. State: Cleanup (single interaction)
"""

# Simple flow - no state preservation needed
# Immediate response with generated link

# Scenario 4: Project Location Setup
"""
FLOW: Add Project GPS Location
1. User: Sends location + "工程編號25001，位置名稱：中環皇后大道中123號"
2. System: Extract project code and location name
3. System: Save GPS coordinates with project
4. System: Confirm location saved
5. State: Cleanup
"""

# Special handling for location data override
# GPS coordinates from message are processed immediately

#---------------------------README END-------------------------------



# Imports
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime

from src.chatbot_service.chatbot_helpers.conversation_state_manager import \
    conversation_state_manager
from src.message_templates.message_response_templates import send_whatsapp_message_back
from src.chatbot_service.langgraph.agent import compiled_graph
from src.chatbot_service.langgraph.message_history import LimitedHistory
from src.chatbot_service.langgraph.state import WorkflowState
from src.routes import api_router
from temporal_app.schedules.scheduler import setup_all_schedules
from temporal_app.client import close_temporal_client, get_temporal_client
from infrastructure.database.database_config import get_environment
from infrastructure.database.database_connection import get_database
from infrastructure.redis_connection.redis_manager import (clear_image_collection,
                                            clear_state, load_previous_state,
                                            redis_manager, save_state)

from src.utils.datetime_standarization_helpers import HK_TZ, get_this_moment    

# Environment variables
account_sid = os.getenv("ACCOUNT_SID")
auth_token = os.getenv("AUTH_TOKEN")
chatbot_waba = os.getenv("WHATSAPP_NUMBER")

# Configure logging first (remove duplicate)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app")


current_env = get_environment()
logging.info(f"env: {current_env}")

#Application Initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    APPLICATION STARTUP SEQUENCE:
    
    1. Initialize Database Connection
    2. Connect to Redis (state management)
    3. Initialize Temporal Client (workflow orchestration)
    4. Setup Scheduled Tasks
    5. Handle graceful shutdown
    
    COMMENT: This is the application lifecycle manager
    Ensures all external services are properly initialized
    """
    
    # Database initialization
    await get_database() #Why no try-except here? Because get_database() already has error handling inside it.
    
    # Redis connection for state management
    try:
        await redis_manager.connect()
        logger.info("✅ Redis initialized successfully")
    except Exception as e:
        logger.error(f"❌ Redis initialization failed: {e}")
        raise
    
    # Temporal client for async workflows
    try:
        await get_temporal_client() 
        logger.info("✅ Temporal client initialized successfully")

        # Setup scheduled tasks (reminders, reports, etc.)
        try:
            
            schedule_result = await setup_all_schedules()    

            if schedule_result.get("status") == "completed":
                successful = schedule_result.get("successful", 0)
                total = schedule_result.get("total", 0)
                logger.info(
                    f"✅ Temporal schedules initialized: {successful}/{total} successful"
                )

                for result in schedule_result.get("results", []):
                    schedule_id = result.get("schedule_id", "unknown")
                    status = result.get("status", "unknown")
                    if status == "success":
                        logger.info(
                            f"  ✓ {schedule_id}: {result.get('message', 'Success')}"
                        )
                    else:
                        logger.warning(
                            f"  ⚠ {schedule_id}: {result.get('message', 'Failed')}"
                        )
            else:
                logger.warning(
                    f"⚠️ Temporal schedule setup completed with issues: {schedule_result}"
                )

        except Exception as schedule_error:
            logger.error(f"⚠️ Temporal schedule initialization failed: {schedule_error}")
            logger.warning(
                "Application will continue without scheduled tasks. Use scripts/setup_temporal.py manually."
            )

    except Exception as e:
        logger.warning(
            f"⚠️ Temporal client initialization failed (this is OK if Temporal server is not running): {e}"
        )
        app.state.temporal_client = None

    yield # Application runs here
    
    
    # Cleanup on shutdown
    try:
        await redis_manager.disconnect()
        logger.info("✅ Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")

    try:
        await close_temporal_client()
        logger.info("✅ Temporal client connection closed")
    except Exception as e:
        logger.error(f"Error closing Temporal client: {e}")


# Create FastAPI app
app = FastAPI(
    title="wls Assistant API",
    description="API for wls Assistant with Temporal workflows and Redis caching",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


app.include_router(api_router)

# Mount static files for attendance HTML
static_dir = Path(__file__).parent / "assets" / "attendance_html" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logging.info(f"📁 Static files mounted at /static from {static_dir}")
else:
    logging.warning(f"⚠️ Static directory not found: {static_dir}")


@app.get("/")
async def root():
    return {
        "message": "wls Assistant API is running",
        "environment": current_env,
        "version": "1.0.0",
        "timestamp": get_this_moment().isoformat(),
    }

 # Test endpoint to verify static files are accessible
@app.get("/test-static")
async def test_static():
    static_file_path = Path(__file__).parent / "assets" / "attendance_html" / "static" / "language_utils.js"
    return {
        "static_file_exists": static_file_path.exists(),
        "static_file_path": str(static_file_path),
        "static_file_size": static_file_path.stat().st_size if static_file_path.exists() else 0
    }


client = Client(account_sid, auth_token)

limited_history = LimitedHistory(max_messages=2)

# Webhook Processing Logic for Twilio WhatsApp
@app.post("/webhook")
async def post_webhook(request: Request):
    """
    MAIN WEBHOOK LOGIC - This is the heart of the system
    
    Flow:
    1. Parse incoming WhatsApp message
    2. Handle special cases (approvals, media)
    3. Load previous conversation state
    4. Merge states intelligently
    5. Execute AI workflow
    6. Save/cleanup state
    7. Send response
    """
    #Message Parsing
    try:
        form_data = await request.form()

        if not form_data or not form_data.get("From"):
            logging.info("Received webhook with missing required fields")
            return HTMLResponse(content="", status_code=200)
        
        # Parse form data from Twilio webhook
        body = form_data.get("Body", "")  # Default to empty string if no body
        sender = form_data.get("From")
        lat = form_data.get("Latitude")
        lon = form_data.get("Longitude")
        logging.info(f"Latitude: {lat}, Longitude: {lon} from message: {body}")

        # Extract media URLs (images, documents)
        media_urls = []
        i = 0
        while True:
            media_url = form_data.get(f"MediaUrl{i}")
            if media_url:
                media_urls.append(media_url)
                logging.info(f"Received media URL {i}: {media_url}")
                i += 1
            else:
                break
        # COMMENT: Twilio sends media as MediaUrl0, MediaUrl1, etc.
        # This loop extracts all media attachments

        if media_urls:
            logging.info(f"Received {len(media_urls)} media URLs: {media_urls}")

        await send_whatsapp_message_back("⏳ Processing your request, please wait a moment... \n⏳ 正在處理您的請求，請稍候...", sender)

        # Check if this is an approval/rejection response for special work applications
        from src.utils.special_work_approval_handler import SpecialWorkApprovalHandler
        is_approval_response = await SpecialWorkApprovalHandler.process_message(sender, body) #from approval/rejection response to special work application
        
        if is_approval_response:
            # COMMENT: This handles supervisor approvals for overtime/special work
            # If it's an approval response, processing ends here
            logging.info(f"Special work approval/rejection processed for {sender}")
            return HTMLResponse(content="", status_code=200)
        
        """
        COMPLEX STATE MANAGEMENT:

        The system maintains conversation state in Redis to handle:
        1. Multi-turn conversations
        2. Image collection workflows  
        3. Form filling across multiple messages
        4. Session timeout detection
        5. Intent transitions

        This is one of the most complex parts of the system.
        """
        previous_state = await load_previous_state(sender)
      
        should_clear_state = False
        if previous_state:
            # EXISTING CONVERSATION
            # 1. Smart session detection
            should_clear_state = False
            from infrastructure.redis_connection.redis_manager import get_image_collection

            collection = await get_image_collection(sender)

            # Smart session detection: Clear old collection if new intent session detected
            should_clear_collection = False

            # 2. Detect new intent sessions
            # Detect if this is a new "add worker" session with different project
            if body and ("add cards" in body.lower() or "card" in body.lower()):
                # Extract project number from current message
                import re
                 # Check for session timeout (30 minutes)
                if collection and collection.get("last_updated"):

                    try:
                        last_updated = datetime.fromisoformat(
                            collection.get("last_updated")
                        )
                        if last_updated.tzinfo is None:
                            last_updated = last_updated.replace(tzinfo=HK_TZ)
                        time_gap = (
                            get_this_moment() - last_updated
                        ).total_seconds()
                        if time_gap > 1800:
                            logging.info(
                                f"Detected session timeout: {time_gap/60:.1f} minutes gap"
                            )
                            should_clear_collection = True
                    except Exception as e:
                        logging.warning(f"Error parsing collection timestamp: {e}")

            if should_clear_collection:
                logging.info("Clearing old Redis collection for new session")
                await clear_image_collection(sender)
                collection = None
                previous_media_urls = []
            else:
                previous_media_urls = previous_state.get("media_urls", [])

            collection = await get_image_collection(sender)

            all_urls = []

            # 3. Media URL deduplication
            # Add new media URLs
            if media_urls:
                all_urls.extend(media_urls) # New media

            # Add collection images if not clearing collection
            if not should_clear_collection and collection and collection.get("images"):
                collection_images = collection.get("images", [])
                logging.info(
                    f"Found existing collection with {len(collection_images)} images"
                )
                all_urls.extend(collection_images)   # Existing collection

            # Add previous media URLs if not clearing collection
            if not should_clear_collection:
                all_urls.extend(previous_media_urls)  # Previous state

            # Deduplicate all URLs using the utility function
            all_media_urls = redis_manager.deduplicate_media_urls(all_urls) # Remove duplicates while preserving order

            # Log the deduplication results with better debugging
            collection_size = len(collection.get("images", [])) if collection else 0
            redis_manager.log_media_urls_state(
                sender, "main.py", all_urls, all_media_urls
            )
            logging.info(
                f"Media URLs deduplicated: collection={collection_size}, previous={len(previous_media_urls)}, new={len(media_urls)}, total={len(all_media_urls)}"
            )

            if should_clear_collection:
                logging.info("🔄 Started new session - processing only current images")

            extracted_fields = previous_state.get("extracted_fields", {})
            if (media_urls and len(media_urls) > 0) or should_clear_collection:
                if "cards_data" in extracted_fields:
                    logging.info(
                        "Clearing previous cards_data due to new images/session"
                    )
                    extracted_fields = {
                        k: v for k, v in extracted_fields.items() if k != "cards_data"
                    }

            image_collection_active = previous_state.get(
                "image_collection_active", False
            ) or bool(media_urls)

            original_body = previous_state.get("original_body", "")
            if collection and collection.get("original_body"):
                collection_body = collection.get("original_body", "")
                if collection_body and (
                    "add cards" in collection_body.lower()
                    or "card" in collection_body.lower()
                ):
                    original_body = collection_body
                    logging.info(
                        f"Using original body from collection: {original_body}"
                    )

            if body and ("add cards" in body.lower() or "card" in body.lower()):
                original_body = body
                logging.info(
                    f"Setting original body from current message: {original_body}"
                )

            # Set status for existing state
            status = (
                "collecting_images"
                if image_collection_active
                else previous_state.get("status", "await_intent")
            )
            
            # 4. Merge states intelligently
            current_state = WorkflowState(
                messages=previous_state.get("messages", [])
                + [
                    {
                        "role": "user",
                        "content": {
                            "Body": body,
                            "From": sender,
                            "MediaUrl0": media_urls[0] if media_urls else None,
                            "Latitude": lat,
                            "Longitude": lon,
                        },
                    }
                ],
                current_intent=previous_state.get("current_intent", ""),
                extracted_fields=extracted_fields,
                validated=previous_state.get("validated", False),
                status=status,
                action_result=previous_state.get("action_result", ""),
                error=previous_state.get("error", False),
                media_urls=all_media_urls,
                image_collection_active=image_collection_active,
                image_collection_processed=previous_state.get(
                    "image_collection_processed", False
                ),
                image_count=len(all_media_urls),
                collected_image_count=len(all_media_urls),
                original_body=original_body,  # Store the original body with project info
                done_command_received=False,
            )
        else:
            # NEW CONVERSATION
            status = "collecting_images" if media_urls else "await_intent"
            original_body = body if body else ""

            current_state = WorkflowState(
                messages=[
                    {
                        "role": "user",
                        "content": {
                            "Body": body,
                            "From": sender,
                            "MediaUrl0": media_urls[0] if media_urls else None,
                            "Latitude": lat,
                            "Longitude": lon,
                        },
                    }
                ],
                current_intent="",
                extracted_fields={},
                validated=False,
                status=status,
                action_result="",
                error=False,
                media_urls=media_urls,
                image_collection_active=bool(media_urls),
                image_collection_processed=False,
                image_count=len(media_urls),
                collected_image_count=len(media_urls),
                original_body=original_body,  # Store the original body
                done_command_received=False,
            )

            """
            AI WORKFLOW EXECUTION:

            The system uses LangGraph to execute a complex conversational AI workflow.
            This is a state machine that processes the conversation through multiple nodes:

            1. Image Collection
            2. Intent Classification  
            3. Document Validation
            4. Entity Extraction
            5. Entity Validation
            6. Database Operations
            7. Response Generation
            """
        try:
            logging.info(f"current_state: {current_state}")
            # Execute the AI workflow
            final_state = await compiled_graph.ainvoke(current_state)
            # COMMENT: compiled_graph is a LangGraph state machine
            # It processes the conversation through multiple AI nodes
            # Each node can modify the state and determine the next step

            # Log the final state to understand what's happening
            logging.info(
                f"final_state after workflow: status='{final_state.get('status')}', "
                f"image_collection_active={final_state.get('image_collection_active')}, "
                f"image_collection_processed={final_state.get('image_collection_processed')}, "
                f"current_intent='{final_state.get('current_intent')}'"
            )

            if (
                previous_state
                and final_state.get("current_intent")
                and final_state.get("extracted_fields")
            ):
                should_clear = conversation_state_manager.should_clear_entire_state(
                    previous_state,
                    final_state.get("current_intent"),
                    final_state.get("extracted_fields"),
                )

                if should_clear:
                    logging.info(
                        f"Clearing state due to new intent classification: {final_state.get('current_intent')}"
                    )
                    await clear_state(sender)
                    await clear_image_collection(sender)
                    logging.info(f"State and image collection cleared for {sender}")

          

            if final_state.get("status") == "temp_end":
                logging.info("Saving state for image collection continuation")
                await save_state(sender, final_state)
            elif (
                final_state.get("image_collection_active")
                and final_state.get("status") == "collecting_images"
            ):
                # Preserve state for ongoing image collection
                logging.info("Preserving state for ongoing image collection")
                await save_state(sender, final_state)
            elif final_state.get("status") == "collecting_images":
                # Preserve state for add_unprocessed_cards intent that's waiting for more images or done command
                logging.info(
                    "Preserving state for add_unprocessed_cards intent in await_intent status"
                )
                await save_state(sender, final_state)
            else:
                logging.info("Workflow completed, proceeding to cleanup")

        except Exception as e:
            # Fallback error handling
            logging.error(f"Error in workflow execution: {str(e)}", exc_info=True)
            await send_whatsapp_message_back(
                "AI而家仲喺開發緊，撞到啲小問題😅麻煩你搵下管理員幫手啦～我哋會慢慢學多啲嘢，希望之後可以幫到你更多～😉",
                sender,
            )
            return HTMLResponse(content="", status_code=200)

        if final_state.get("status") == "temp_end":
            response = MessagingResponse()
            result_message = (
                final_state.get("action_result")
                or "AI而家仲喺開發緊，撞到啲小問題😅麻煩你搵下管理員幫手啦～我哋會慢慢學多啲嘢，希望之後可以幫到你更多～😉"
            )

            await send_whatsapp_message_back(result_message, sender)
            logging.info(f"Sent result message to {sender}")
            return HTMLResponse(content="", status_code=200)

        # State Cleanup Logic
        # Only cleanup if the workflow is truly complete (not in image collection, waiting for add_unprocessed_cards, or waiting for location data)
        """
        INTELLIGENT STATE CLEANUP:

        The system needs to decide when to preserve state vs when to clean up.
        This is critical for user experience and system performance.
        """
        # Check if workflow should continue or complete
        is_image_collection_active = (
            final_state.get("image_collection_active")
            and final_state.get("status") == "collecting_images"
        )
        is_add_unprocessed_cards_waiting = (
            final_state.get("status") == "await_intent"
            and final_state.get("current_intent") == "add_unprocessed_cards"
        )
        is_waiting_for_location_data = (
            final_state.get("current_intent") == "add_project_gps"
            and final_state.get("status") in ["await_field", "error"]
            and final_state.get("action_result")
            and (
                "位置資料" in final_state.get("action_result", "")
                or "位置" in final_state.get("action_result", "")
                or "location" in final_state.get("action_result", "").lower()
            )
        )

        if not (
            is_image_collection_active
            or is_add_unprocessed_cards_waiting
            or is_waiting_for_location_data
        ):
            logging.info("Workflow completed, cleaning up conversation state")
            # Conversation complete - cleanup
            await conversation_state_manager.cleanup_conversation_state(
                sender, final_state
            )
        else:
            if is_waiting_for_location_data:
                logging.info(
                    "Waiting for location data for add_project_gps intent, preserving conversation state"
                )
            else:
                logging.info(
                    "Image collection or add_unprocessed_cards intent still active, preserving conversation state"
                )

        return HTMLResponse(content="", status_code=200)

    except Exception as e:
        logging.error(f"Error in webhook processing: {str(e)}", exc_info=True)
        return HTMLResponse(content="", status_code=200)
