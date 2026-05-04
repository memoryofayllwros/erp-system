"""
Temporal.io Client Configuration
"""

import logging
import os
from typing import Any, Dict, Optional

from temporalio.client import Client

from .config import get_environment_info, get_temporal_config

logger = logging.getLogger(__name__)

# Global client instance
_temporal_client: Optional[Client] = None


async def get_temporal_client() -> Client:
    """
    Get or create Temporal client instance
    """
    global _temporal_client

    if _temporal_client is None:
        _temporal_client = await create_temporal_client()

    return _temporal_client


async def create_temporal_client() -> Client:
    """
    Create Temporal client with configuration
    """
    # Get configuration
    config = get_temporal_config()
    env_info = get_environment_info()

    logger.info(f"Creating Temporal client with config: {config}")
    logger.info(f"Environment info: {env_info}")

    try:
        # Connect to Temporal server
        client = await Client.connect(
            target_host=config["host"], namespace=config["namespace"]
        )
        logger.info(
            f"✅ Successfully connected to Temporal at {config['host']} with namespace '{config['namespace']}'"
        )
        return client

    except Exception as e:
        logger.error(
            f"❌ Failed to connect to Temporal at {config['host']} with namespace '{config['namespace']}': {str(e)}"
        )

        # If namespace doesn't exist, try with 'default' namespace
        if "namespace" in str(e).lower() and config["namespace"] != "default":
            logger.info(
                f"Trying with 'default' namespace instead of '{config['namespace']}'"
            )
            try:
                client = await Client.connect(
                    target_host=config["host"], namespace="default"
                )
                logger.info(
                    f"✅ Successfully connected to Temporal with 'default' namespace"
                )
                return client
            except Exception as fallback_error:
                logger.error(
                    f"❌ Failed to connect with 'default' namespace: {str(fallback_error)}"
                )

        # If we failed with the configured host and we're not in Docker, try localhost as fallback
        if config["host"] != "localhost:7233" and not env_info["in_docker"]:
            logger.info("Trying localhost:7233 as fallback")
            try:
                client = await Client.connect(
                    target_host="localhost:7233",
                    namespace="default",  # Use default namespace for fallback
                )
                logger.info(
                    "✅ Successfully connected to localhost:7233 with 'default' namespace"
                )
                return client
            except Exception as localhost_error:
                logger.error(
                    f"❌ Failed to connect to localhost:7233: {str(localhost_error)}"
                )

        # If all attempts failed, provide helpful error message
        error_msg = f"""
Failed to connect to Temporal server. 

Configuration used:
- Host: {config['host']}
- Namespace: {config['namespace']}
- In Docker: {env_info['in_docker']}

Attempts made:
1. {config['host']} with namespace '{config['namespace']}'
2. {config['host']} with namespace 'default' (if different from configured)
3. localhost:7233 with namespace 'default' (if not in Docker)

Original error: {str(e)}

To fix this:
1. Ensure Temporal server is running
2. Check if namespace '{config['namespace']}' exists
3. Verify network connectivity
4. Check environment variables: TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE
        """

        logger.error(error_msg)
        raise Exception(error_msg)


async def close_temporal_client():
    """
    Close the Temporal client connection
    """
    global _temporal_client

    if _temporal_client:
        try:
            # Check which close method is available
            if hasattr(_temporal_client, "aclose"):
                await _temporal_client.aclose()
            elif hasattr(_temporal_client, "close"):
                await _temporal_client.close()
            else:
                logger.warning("No close method found on Temporal client")
        except Exception as e:
            logger.error(f"Error closing Temporal client: {e}")
        finally:
            _temporal_client = None


def get_client_status() -> Dict[str, Any]:
    """
    Get current client status for debugging
    """
    return {
        "client_initialized": _temporal_client is not None,
        "config": get_temporal_config(),
        "environment": get_environment_info(),
    }
