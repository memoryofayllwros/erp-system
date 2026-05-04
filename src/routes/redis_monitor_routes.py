"""
Redis and Temporal Monitoring Routes
Provides monitoring endpoints for Redis and Temporal services.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

from src.utils.datetime_standarization_helpers import get_this_moment
from temporal_app.client import get_temporal_client
from infrastructure.database.database_connection import get_database
from infrastructure.redis_connection.redis_manager import (clear_image_collection,
                                            clear_state, redis_manager)

router = APIRouter(prefix="/monitor", tags=["Monitoring"])
logger = logging.getLogger(__name__)


@router.get("/redis/status", operation_id="get_redis_status")
async def redis_status() -> Dict[str, Any]:
    """
    Get Redis connection status
    """
    try:
        # Check Redis connection
        is_connected = await redis_manager.ping()

        # Get Redis info
        info = await redis_manager.get_info() if is_connected else {}

        # Format response
        return {
            "status": "connected" if is_connected else "disconnected",
            "timestamp": get_this_moment().isoformat(),
            "info": {
                "version": info.get("redis_version", "unknown"),
                "uptime_days": info.get("uptime_in_days", "unknown"),
                "connected_clients": info.get("connected_clients", "unknown"),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "total_connections_received": info.get(
                    "total_connections_received", "unknown"
                ),
            },
        }
    except Exception as e:
        logger.error(f"Error checking Redis status: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get("/redis/keys", operation_id="get_redis_keys")
async def redis_keys(pattern: str = "*", limit: int = 100) -> Dict[str, Any]:
    """
    Get Redis keys matching a pattern
    """
    try:
        # Get keys
        keys = await redis_manager.keys(pattern)

        return {
            "status": "success",
            "count": len(keys),
            "keys": keys[:limit],
            "timestamp": get_this_moment().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error getting Redis keys: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get("/redis/memory", operation_id="get_redis_memory")
async def redis_memory() -> Dict[str, Any]:
    """
    Get Redis memory usage
    """
    try:
        # Get memory info
        info = await redis_manager.get_info()

        memory_info = {
            "used_memory": info.get("used_memory", "unknown"),
            "used_memory_human": info.get("used_memory_human", "unknown"),
            "used_memory_peak": info.get("used_memory_peak", "unknown"),
            "used_memory_peak_human": info.get("used_memory_peak_human", "unknown"),
            "maxmemory": info.get("maxmemory", "unknown"),
            "maxmemory_human": info.get("maxmemory_human", "unknown"),
            "maxmemory_policy": info.get("maxmemory_policy", "unknown"),
        }

        return {
            "status": "success",
            "memory_info": memory_info,
            "timestamp": get_this_moment().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error getting Redis memory info: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.post(
    "/redis/clear-conversation/{sender}", operation_id="clear_redis_conversation_state"
)
async def clear_conversation_state(sender: str) -> Dict[str, Any]:
    """
    Clear conversation state for a specific sender

    Args:
        sender: The WhatsApp sender ID (e.g., "whatsapp:+85264760285")

    Returns:
        Status of the operation
    """
    try:
        # Ensure the sender has the whatsapp: prefix
        if not sender.startswith("whatsapp:"):
            sender = f"whatsapp:{sender}"

        logger.info(f"Clearing conversation state for: {sender}")

        # Clear the main conversation state
        state_cleared = await clear_state(sender)

        # Clear the image collection
        image_cleared = await clear_image_collection(sender)

        # Also try to clear using the redis_manager directly
        redis_cleared = False
        try:
            await redis_manager.clear_state(sender)
            redis_cleared = True
        except Exception as e:
            logger.warning(f"Redis manager clear failed: {str(e)}")

        success = state_cleared or image_cleared or redis_cleared

        return {
            "status": "success" if success else "partial_success",
            "sender": sender,
            "operations": {
                "state_cleared": state_cleared,
                "image_collection_cleared": image_cleared,
                "redis_manager_cleared": redis_cleared,
            },
            "message": (
                f"Conversation state cleared for {sender}"
                if success
                else f"Partial success clearing state for {sender}"
            ),
            "timestamp": get_this_moment().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error clearing conversation state for {sender}: {str(e)}")
        return {
            "status": "error",
            "sender": sender,
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get(
    "/redis/conversation-state/{sender}", operation_id="get_redis_conversation_state"
)
async def get_conversation_state(sender: str) -> Dict[str, Any]:
    """
    Get conversation state for a specific sender

    Args:
        sender: The WhatsApp sender ID

    Returns:
        Current conversation state
    """
    try:
        # Ensure the sender has the whatsapp: prefix
        if not sender.startswith("whatsapp:"):
            sender = f"whatsapp:{sender}"

        # Get conversation state
        state = await redis_manager.load_state(sender)

        # Get image collection
        from infrastructure.redis_connection.redis_manager import get_image_collection

        collection = await get_image_collection(sender)

        return {
            "status": "success",
            "sender": sender,
            "has_state": state is not None,
            "has_image_collection": collection is not None,
            "state": state if state else None,
            "image_collection": collection if collection else None,
            "timestamp": get_this_moment().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting conversation state for {sender}: {str(e)}")
        return {
            "status": "error",
            "sender": sender,
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get("/temporal/status", operation_id="get_temporal_status")
async def temporal_status() -> Dict[str, Any]:
    """
    Get Temporal service status
    """
    try:
        # Get Temporal client
        client = await get_temporal_client()

        # Check connection by getting namespace
        namespace = await client.get_namespace()

        # Get cluster info
        cluster_info = await client.workflow_service.get_cluster_info()

        return {
            "status": "connected",
            "namespace": namespace,
            "server_version": cluster_info.server_version,
            "cluster_name": cluster_info.cluster_name,
            "timestamp": get_this_moment().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error checking Temporal status: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get("/temporal/workflows", operation_id="list_temporal_workflows")
async def list_workflows(
    workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20
) -> Dict[str, Any]:
    """
    List Temporal workflows
    """
    try:
        # Get Temporal client
        client = await get_temporal_client()

        # Build query
        query = {}
        if workflow_id:
            query["workflow_id"] = workflow_id

        # Map status string to enum
        if status:
            from temporalio.client import WorkflowExecutionStatus

            status_map = {
                "running": WorkflowExecutionStatus.RUNNING,
                "completed": WorkflowExecutionStatus.COMPLETED,
                "failed": WorkflowExecutionStatus.FAILED,
                "canceled": WorkflowExecutionStatus.CANCELED,
                "terminated": WorkflowExecutionStatus.TERMINATED,
                "continued_as_new": WorkflowExecutionStatus.CONTINUED_AS_NEW,
                "timed_out": WorkflowExecutionStatus.TIMED_OUT,
            }
            if status.lower() in status_map:
                query["status"] = status_map[status.lower()]

        # List workflows
        workflows = []
        async for workflow in client.list_workflows(**query, page_size=limit):
            workflows.append(
                {
                    "workflow_id": workflow.id,
                    "run_id": workflow.run_id,
                    "workflow_type": workflow.type,
                    "status": str(workflow.status).split(".")[-1],
                    "start_time": (
                        workflow.start_time.isoformat() if workflow.start_time else None
                    ),
                    "execution_time": (
                        workflow.execution_time.isoformat()
                        if workflow.execution_time
                        else None
                    ),
                    "close_time": (
                        workflow.close_time.isoformat() if workflow.close_time else None
                    ),
                }
            )

            if len(workflows) >= limit:
                break

        return {
            "status": "success",
            "count": len(workflows),
            "workflows": workflows,
            "timestamp": get_this_moment().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error listing Temporal workflows: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.post(
    "/temporal/workflow/{workflow_id}/cancel", operation_id="cancel_temporal_workflow"
)
async def cancel_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Cancel a Temporal workflow
    """
    try:
        # Get Temporal client
        client = await get_temporal_client()

        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)

        # Cancel workflow
        await handle.cancel()

        return {
            "status": "success",
            "message": f"Workflow {workflow_id} cancelled",
            "timestamp": get_this_moment().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error cancelling workflow {workflow_id}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_this_moment().isoformat(),
        }


@router.get("/health", operation_id="get_monitor_health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for both Redis and Temporal
    """
    redis_healthy = False
    temporal_healthy = False

    # Check Redis
    try:
        redis_healthy = await redis_manager.ping()
    except Exception as e:
        logger.warning(f"Redis health check failed: {str(e)}")

    # Check Temporal
    try:
        client = await get_temporal_client()
        await client.workflow_service.get_cluster_info()
        temporal_healthy = True
    except Exception as e:
        logger.warning(f"Temporal health check failed: {str(e)}")

    # Overall health status
    is_healthy = redis_healthy and temporal_healthy

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "services": {
            "redis": "healthy" if redis_healthy else "unhealthy",
            "temporal": "healthy" if temporal_healthy else "unhealthy",
        },
        "timestamp": get_this_moment().isoformat(),
    }


@router.get("/readiness", operation_id="get_monitor_readiness")
async def readiness_check():
    """
    Kubernetes readiness probe endpoint
    Returns 200 only if all critical services are ready
    """
    try:
        # Check critical services only
        redis_ready = await redis_manager.ping()
        db = await get_database()  # This will throw if DB is not ready

        if redis_ready:
            return {"status": "ready"}
        else:
            return {"status": "not ready", "reason": "Redis not available"}, 503

    except Exception as e:
        return {"status": "not ready", "reason": str(e)}, 503


@router.get("/liveness", operation_id="get_monitor_liveness")
async def liveness_check():
    """
    Kubernetes liveness probe endpoint
    Simple check to verify the application is alive
    """
    return {"status": "alive", "timestamp": get_this_moment().isoformat()}
