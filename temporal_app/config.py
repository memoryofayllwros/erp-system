"""
Temporal.io Configuration
"""

import os
from typing import Any, Dict

# Default Temporal.io configuration
DEFAULT_TEMPORAL_CONFIG = {
    "host": "localhost:7233",
    "namespace": "default",
    "task_queue": "attendance-task-queue",
    "max_concurrent_activities": 10,
    "max_concurrent_workflows": 5,
    "retry_policy": {
        "initial_interval": 10,  # seconds
        "maximum_interval": 300,  # 5 minutes
        "maximum_attempts": 3,
        "backoff_coefficient": 2.0,
    },
}


def get_temporal_config() -> Dict[str, Any]:
    """
    Get Temporal.io configuration from environment variables with defaults
    """
    config = DEFAULT_TEMPORAL_CONFIG.copy()

    # Override with environment variables
    if os.getenv("TEMPORAL_ADDRESS"):
        config["host"] = os.getenv("TEMPORAL_ADDRESS")

    if os.getenv("TEMPORAL_NAMESPACE"):
        config["namespace"] = os.getenv("TEMPORAL_NAMESPACE")

    if os.getenv("TEMPORAL_TASK_QUEUE"):
        config["task_queue"] = os.getenv("TEMPORAL_TASK_QUEUE")

    # Check if running in Docker
    if os.path.exists("/.dockerenv"):
        config["host"] = "temporal:7233"

    return config


def get_environment_info() -> Dict[str, Any]:
    """
    Get information about the current environment for debugging
    """
    return {
        "in_docker": os.path.exists("/.dockerenv"),
        "temporal_host": get_temporal_config()["host"],
        "temporal_namespace": get_temporal_config()["namespace"],
        "temporal_task_queue": get_temporal_config()["task_queue"],
        "python_path": os.getenv("PYTHONPATH", ""),
        "current_working_dir": os.getcwd(),
        "environment_variables": {
            "TEMPORAL_ADDRESS": os.getenv("TEMPORAL_ADDRESS"),
            "TEMPORAL_NAMESPACE": os.getenv("TEMPORAL_NAMESPACE"),
            "TEMPORAL_TASK_QUEUE": os.getenv("TEMPORAL_TASK_QUEUE"),
        },
    }


# Environment-specific configurations
ENVIRONMENT_CONFIGS = {
    "development": {
        "host": "localhost:7233",
        "namespace": "default",
        "task_queue": "attendance-task-queue-dev",
        "max_concurrent_activities": 5,
        "max_concurrent_workflows": 3,
    },
    "testing": {
        "host": "localhost:7233",
        "namespace": "test",
        "task_queue": "attendance-task-queue-test",
        "max_concurrent_activities": 2,
        "max_concurrent_workflows": 1,
    },
    "production": {
        "host": "temporal:7233",  # Docker service name
        "namespace": "production",
        "task_queue": "attendance-task-queue-prod",
        "max_concurrent_activities": 20,
        "max_concurrent_workflows": 10,
    },
}


def get_environment_config(env: str = None) -> Dict[str, Any]:
    """
    Get configuration for a specific environment
    """
    if not env:
        env = os.getenv("ENVIRONMENT", "development")

    base_config = DEFAULT_TEMPORAL_CONFIG.copy()
    env_config = ENVIRONMENT_CONFIGS.get(env, {})

    # Merge configurations
    base_config.update(env_config)

    return base_config
