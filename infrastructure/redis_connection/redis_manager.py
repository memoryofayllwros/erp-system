"""
Redis Manager for WLS Assistant Assistant
Handles Redis connections, operations, and fallback mechanisms.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from src.utils.datetime_standarization_helpers import get_this_moment, HK_TZ
import redis.asyncio as redis

from .redis_config import RedisConfig, get_redis_config

redis_key_prefix = os.getenv("REDIS_KEY_PREFIX")

logger = logging.getLogger(__name__)


class ImageCollectionError(Exception):
    """Custom exception for image collection errors"""

    pass


class RedisManager:
    """Redis manager with connection pooling and fallback mechanisms"""

    _in_memory_data = {}
    _in_memory_ttl = {}

    def __init__(self, config: Optional[RedisConfig] = None):
        self._client = None
        self._pool = None
        self._config = config
        self._connected = False
        self._last_error = None
        self._last_error_time = None
        self._error_count = 0
        self._circuit_open = False
        self._in_memory_mode = False
        self._logger = logging.getLogger(__name__)

    async def _create_redis_client_from_url(self, host: str) -> Optional[redis.Redis]:
        """Create a Redis client from a host URL or hostname"""
        try:
            # Parse host and port
            if ":" in host:
                hostname, port = host.split(":")
                port = int(port)
            else:
                hostname = host
                port = 6379  # Default Redis port

            # Create connection kwargs
            kwargs = {
                "host": hostname,
                "port": port,
                "db": self._config.db if self._config else 0,
                "decode_responses": True,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "retry_on_timeout": True,
            }

            # Create Redis client
            client = redis.Redis(**kwargs)

            # Test connection
            await client.ping()

            self._logger.info(f"Successfully connected to Redis at {host}")
            return client
        except Exception as e:
            self._logger.warning(f"Failed to connect to Redis at {host}: {str(e)}")
            return None

    async def connect(self):
        """Connect to Redis"""
        if self._connected:
            return True

        try:
            # Get Redis configuration
            self._config = get_redis_config()

            # Try to connect using the configured host
            if self._config:
                # Try with connection kwargs first
                try:
                    # Create Redis client
                    self._client = redis.Redis(**self._config.get_connection_kwargs())

                    # Test connection
                    await self._client.ping()

                    self._connected = True
                    self._in_memory_mode = False
                    self._circuit_open = False
                    self._error_count = 0
                    logger.info(
                        f"Connected to Redis at {self._config.get_connection_url()}"
                    )

                    return True
                except Exception as e:
                    logger.warning(f"Failed to connect to primary Redis host: {str(e)}")
                    # Close the client if it was created
                    if self._client:
                        await self._client.close()
                        self._client = None

            # Try fallback hosts
            fallback_hosts = (
                self._config.fallback_hosts
                if self._config
                else [
                    "redis",
                    "172.18.0.2",  # Actual Redis container IP
                    "redis-container",
                    "localhost",
                    "127.0.0.1",
                ]
            )

            for host in fallback_hosts:
                self._client = await self._create_redis_client_from_url(host)
                if self._client:
                    logger.info(
                        f"Successfully connected to fallback Redis host: {host}"
                    )
                    self._connected = True
                    self._in_memory_mode = False
                    self._circuit_open = False
                    self._error_count = 0

                    # Update config with working host if possible
                    if self._config:
                        self._config.host = host

                    return True

            # If we get here, all connection attempts failed
            raise Exception("All Redis connection attempts failed")

        except Exception as e:
            self._last_error = str(e)
            self._last_error_time = get_this_moment()
            self._error_count += 1
            self._connected = False
            self._in_memory_mode = True

            logger.error(f"Failed to connect to Redis: {str(e)}")
            logger.warning("Falling back to in-memory mode")

            return False

    async def close(self):
        """Close Redis connection"""
        if not self._connected or not self._client:
            return

        try:
            await self._client.close()
            self._connected = False
            logger.info("Closed Redis connection")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {str(e)}")

    # Alias for disconnect to maintain compatibility
    async def disconnect(self):
        """Alias for close() method"""
        await self.close()

    @asynccontextmanager
    async def get_client(self):
        """Context manager for Redis client with automatic error handling"""
        try:
            if self._client is None:
                # Try to connect if client is None
                await self.connect()
                if self._client is None:
                    # If still None, create a temporary client with default settings
                    # Try multiple fallback hosts
                    fallback_hosts = [
                        "redis",
                        "172.18.0.2",  # Actual Redis container IP
                        "redis-container",
                        "localhost",
                        "127.0.0.1",
                    ]

                    temp_client = None
                    for host in fallback_hosts:
                        temp_client = await self._create_redis_client_from_url(host)
                        if temp_client:
                            self._logger.warning(
                                f"Connected to fallback Redis host: {host}"
                            )
                            break

                    if temp_client is None:
                        # If all fallbacks fail, create a basic client (will likely fail)
                        self._logger.warning(
                            "All Redis fallbacks failed, using basic client"
                        )
                        temp_client = redis.Redis(
                            host="localhost", port=6379, decode_responses=True
                        )

                    yield temp_client
                    await temp_client.close()
                    return

            yield self._client
        except redis.ConnectionError as e:
            self._logger.error(f"Redis connection error: {str(e)}")
            self._connected = False
            raise
        except redis.TimeoutError as e:
            self._logger.error(f"Redis timeout error: {str(e)}")
            raise
        except Exception as e:
            self._logger.error(f"Redis operation error: {str(e)}")
            raise

    def _custom_encoder(self, obj):
        """Custom JSON encoder for complex objects"""
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, "__str__"):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    async def ping(self) -> bool:
        """Check if Redis is available"""
        # If circuit is open, don't try to connect
        if self._circuit_open:
            # Check if we should retry
            if (
                self._last_error_time
                and (get_this_moment() - self._last_error_time).total_seconds() > 30
            ):
                # Reset circuit breaker
                self._circuit_open = False
                self._error_count = 0
            else:
                return False

        # If not connected, try to connect
        if not self._connected:
            await self.connect()

        if not self._connected:
            return False

        try:
            # Try to ping Redis
            result = await self._client.ping()
            return result
        except Exception as e:
            self._last_error = str(e)
            self._last_error_time = get_this_moment()
            self._error_count += 1
            self._connected = False

            # Open circuit breaker if too many errors
            if self._error_count >= 5:
                self._circuit_open = True
                logger.warning("Circuit breaker opened due to too many Redis errors")

            logger.error(f"Redis ping failed: {str(e)}")
            return False

    async def get(self, key: str) -> Any:
        """Get a value from Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return self._get_in_memory(key)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return self._get_in_memory(key)

            # Get value from Redis
            value = await self._client.get(key)

            if value is None:
                return None

            # Parse JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value.decode("utf-8")

        except Exception as e:
            self._handle_error(f"Error getting value for key {key}: {str(e)}")
            return self._get_in_memory(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set a value in Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return await self._set_in_memory(key, value, ex)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return await self._set_in_memory(key, value, ex)

            # Serialize value
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            elif isinstance(value, (int, float, bool)):
                serialized = str(value)
            else:
                serialized = value

            # Set value in Redis
            if ex:
                await self._client.setex(key, ex, serialized)
            else:
                await self._client.set(key, serialized)

            return True

        except Exception as e:
            self._handle_error(f"Error setting value for key {key}: {str(e)}")
            return await self._set_in_memory(key, value, ex)

    async def delete(self, key: str) -> int:
        """Delete a key from Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return await self._delete_in_memory(key)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return await self._delete_in_memory(key)

            # Delete key from Redis
            return await self._client.delete(key)

        except Exception as e:
            self._handle_error(f"Error deleting key {key}: {str(e)}")
            return await self._delete_in_memory(key)

    async def keys(self, pattern: str) -> List[str]:
        """Get keys matching a pattern from Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return await self._keys_in_memory(pattern)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return await self._keys_in_memory(pattern)

            # Get keys from Redis
            keys = await self._client.keys(pattern)

            # Decode keys
            return [key.decode("utf-8") for key in keys]

        except Exception as e:
            self._handle_error(
                f"Error getting keys matching pattern {pattern}: {str(e)}"
            )
            return await self._keys_in_memory(pattern)

    # Alias for backward compatibility
    async def get_keys(self, pattern: str, limit: int = 100) -> List[str]:
        """Alias for keys() method with limit parameter"""
        keys = await self.keys(pattern)
        return keys[:limit] if limit else keys

    async def ttl(self, key: str) -> int:
        """Get TTL for a key from Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return await self._ttl_in_memory(key)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return await self._ttl_in_memory(key)

            # Get TTL from Redis
            return await self._client.ttl(key)

        except Exception as e:
            self._handle_error(f"Error getting TTL for key {key}: {str(e)}")
            return await self._ttl_in_memory(key)

    async def expire(self, key: str, ex: int) -> bool:
        """Set expiration for a key in Redis with fallback to in-memory store"""
        if self._in_memory_mode:
            return await self._expire_in_memory(key, ex)

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return await self._expire_in_memory(key, ex)

            # Set expiration in Redis
            return await self._client.expire(key, ex)

        except Exception as e:
            self._handle_error(f"Error setting expiration for key {key}: {str(e)}")
            return await self._expire_in_memory(key, ex)

    async def info(self) -> Dict[str, Any]:
        """Get Redis server info"""
        if self._in_memory_mode:
            return {
                "mode": "in_memory",
                "keys": len(self._in_memory_data),
                "memory_usage_human": "N/A",
                "redis_version": "N/A",
            }

        try:
            if not self._connected:
                await self.connect()

            if not self._connected:
                return {
                    "mode": "disconnected",
                    "last_error": self._last_error,
                    "last_error_time": (
                        self._last_error_time.isoformat()
                        if self._last_error_time
                        else None
                    ),
                    "error_count": self._error_count,
                }

            # Get info from Redis
            info = await self._client.info()

            # Extract relevant info
            return {
                "mode": "connected",
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "total_connections_received": info.get("total_connections_received", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
            }

        except Exception as e:
            self._handle_error(f"Error getting Redis info: {str(e)}")
            return {
                "mode": "error",
                "error": str(e),
                "last_error": self._last_error,
                "last_error_time": (
                    self._last_error_time.isoformat() if self._last_error_time else None
                ),
                "error_count": self._error_count,
            }

    # --- State Management Methods ---

    async def load_state(self, sender: str) -> Optional[Dict]:
        """Load workflow state for a sender"""
        try:
            async with self.get_client() as client:
                key = (
                    self._config.get_state_key(sender)
                    if self._config
                    else f"{redis_key_prefix}:state:{sender}"
                )
                value = await client.get(key)
                if value:
                    state = json.loads(value)
                    # Ensure media_urls field exists for backward compatibility
                    if "media_urls" not in state:
                        state["media_urls"] = []
                    self._logger.debug(f"Loaded state for sender: {sender}")
                    return state
                return None
        except Exception as e:
            self._logger.error(f"Error loading state for {sender}: {str(e)}")
            return None

    async def save_state(
        self, sender: str, state: Dict, ttl: Optional[int] = None
    ) -> bool:
        """Save workflow state for a sender with TTL"""
        try:
            # Ensure media_urls field exists for backward compatibility
            if "media_urls" not in state:
                state["media_urls"] = []

            state_json = json.dumps(state, default=self._custom_encoder)

            # Add fallback value for ttl if config is None
            if ttl is None:
                if self._config is None:
                    ttl = 86400  # Default 24 hours if config is None
                else:
                    ttl = self._config.state_ttl

            async with self.get_client() as client:
                key = (
                    self._config.get_state_key(sender)
                    if self._config
                    else f"{redis_key_prefix}:state:{sender}"
                )
                await client.setex(key, ttl, state_json)
                self._logger.debug(f"Saved state for sender: {sender} (TTL: {ttl}s)")
                return True
        except Exception as e:
            self._logger.error(f"Error saving state for {sender}: {str(e)}")
            return False

    async def clear_state(self, sender: str) -> bool:
        """Clear workflow state and image collection for a sender - comprehensive cleanup"""
        try:
            async with self.get_client() as client:
                cleared_keys = []

                # Handle case when config is None
                if self._config is None:
                    state_key = f"{redis_key_prefix}:state:{sender}"
                    images_key = f"{redis_key_prefix}:images:{sender}"
                else:
                    state_key = self._config.get_state_key(sender)
                    images_key = self._config.get_images_key(sender)

                # 1. Clear main state and image keys
                main_keys = [state_key, images_key]
                for key in main_keys:
                    if await client.exists(key):
                        result = await client.delete(key)
                        if result:
                            cleared_keys.append(key)

                # 2. Clear any additional state-related keys with patterns
                state_patterns = [
                    f"{redis_key_prefix}:state:{sender}:*",  # Any sub-state keys
                    f"{redis_key_prefix}:temp_state:{sender}:*",  # Temporary state
                    f"{redis_key_prefix}:session:{sender}:*",  # Session data
                    f"{redis_key_prefix}:cache:{sender}:*",  # Cached data
                ]

                for pattern in state_patterns:
                    try:
                        keys = await client.keys(pattern)
                        if keys:
                            deleted_count = await client.delete(*keys)
                            if deleted_count > 0:
                                cleared_keys.extend(keys)
                                self._logger.debug(
                                    f"Cleared {deleted_count} keys matching pattern '{pattern}' for {sender}"
                                )
                    except Exception as pattern_error:
                        self._logger.warning(
                            f"Error clearing pattern '{pattern}' for {sender}: {str(pattern_error)}"
                        )

                # 3. Clear any other wls-assistant keys for this sender
                general_pattern = f"{redis_key_prefix}:*:{sender}"
                try:
                    keys = await client.keys(general_pattern)
                    if keys:
                        # Filter out keys we've already cleared to avoid double-deletion
                        remaining_keys = [k for k in keys if k not in cleared_keys]
                        if remaining_keys:
                            deleted_count = await client.delete(*remaining_keys)
                            if deleted_count > 0:
                                cleared_keys.extend(remaining_keys)
                                self._logger.debug(
                                    f"Cleared {deleted_count} additional wls-assistant keys for {sender}"
                                )
                except Exception as general_error:
                    self._logger.warning(
                        f"Error clearing general pattern for {sender}: {str(general_error)}"
                    )

                # 4. Clear any hash fields that might contain state data
                try:
                    hash_patterns = [
                        f"{redis_key_prefix}:metadata:{sender}",
                        f"{redis_key_prefix}:user_data:{sender}",
                        f"{redis_key_prefix}:conversation:{sender}",
                    ]

                    for hash_key in hash_patterns:
                        if await client.exists(hash_key):
                            # Clear specific hash fields related to state
                            state_fields = [
                                "status",
                                "intent",
                                "fields",
                                "validation",
                                "processing",
                            ]
                            for field in state_fields:
                                await client.hdel(hash_key, field)
                            self._logger.debug(
                                f"Cleared state-related hash fields from {hash_key} for {sender}"
                            )

                except Exception as hash_error:
                    self._logger.warning(
                        f"Error clearing hash fields for {sender}: {str(hash_error)}"
                    )

                total_cleared = len(cleared_keys)
                if total_cleared > 0:
                    self._logger.info(
                        f"Comprehensive state cleanup completed for {sender}: cleared {total_cleared} keys"
                    )
                else:
                    self._logger.debug(f"No state keys found to clear for {sender}")

                return True

        except Exception as e:
            self._logger.error(
                f"Error in comprehensive state cleanup for {sender}: {str(e)}"
            )
            return False

    async def add_image_to_collection(
        self,
        sender: str,
        media_url: str,
        collection_ttl: Optional[int] = None,
        original_body: Optional[str] = None,
    ) -> int:
        """
        Add an image URL to the user's image collection.
        Returns the current collection count.
        """
        try:
            key = self._config.get_images_key(sender)
            collection_ttl = collection_ttl or self._config.image_collection_ttl

            async with self.get_client() as client:
                # Get existing collection or create new one
                collection_data = await client.get(key)
                if collection_data:
                    collection = json.loads(collection_data)
                else:
                    collection = {
                        "images": [],
                        "created_at": get_this_moment().isoformat(),
                        "last_updated": get_this_moment().isoformat(),
                        "sender": sender,
                        "version": "1.0",  # For future compatibility
                        "original_body": "",  # Store the original body with project info
                    }

                # Update original body if provided and not already set
                if original_body and (
                    not collection.get("original_body")
                    or "project" in original_body.lower()
                    or "工程" in original_body
                ):
                    collection["original_body"] = original_body
                    logging.info(
                        f"Updated original body in collection: {original_body}"
                    )

                # Add new image if not already present
                if media_url not in collection["images"]:
                    collection["images"].append(media_url)
                    collection["last_updated"] = get_this_moment().isoformat()

                    # Save back to Redis with TTL
                    await client.setex(
                        key,
                        collection_ttl,
                        json.dumps(collection, default=self._custom_encoder),
                    )

                    logging.info(
                        f"Added image to collection for {sender}. "
                        f"Total images: {len(collection['images'])}, TTL: {collection_ttl}s"
                    )

                return len(collection["images"])

        except Exception as e:
            logging.error(f"Error adding image to collection for {sender}: {str(e)}")
            return 0

    async def get_image_collection(self, sender: str) -> Optional[Dict]:
        """Get the current image collection for a user"""
        try:
            if self._config is None:
                key = f"{redis_key_prefix}:images:{sender}"
            else:
                key = self._config.get_images_key(sender)

            async with self.get_client() as client:
                collection_data = await client.get(key)
                if collection_data:
                    collection = json.loads(collection_data)
                    logging.info(
                        f"collection in get_image_collection in redis_manager: {collection}"
                    )

                    image_count = len(collection.get("images", []))
                    self._logger.debug(
                        f"Retrieved image collection for {sender}: {image_count} images"
                    )

                    # Add TTL information for monitoring
                    ttl = await client.ttl(key)
                    if ttl > 0:
                        collection["_ttl_seconds"] = ttl

                    return collection

                return None

        except Exception as e:
            self._logger.error(f"Error getting image collection for {sender}: {str(e)}")
            return None

    async def clear_image_collection(self, sender: str) -> bool:
        """Clear the image collection for a user - comprehensive cleanup of all related Redis keys"""
        try:
            async with self.get_client() as client:
                cleared_keys = []

                # 1. Clear the main image collection key
                if self._config is None:
                    main_key = f"{redis_key_prefix}:images:{sender}"
                else:
                    main_key = self._config.get_images_key(sender)

                result = await client.delete(main_key)
                if result:
                    cleared_keys.append(main_key)
                    self._logger.info(f"Cleared main image collection key for {sender}")
                else:
                    self._logger.debug(
                        f"No main image collection found to clear for {sender}"
                    )

                # 2. Clear any additional image-related keys with patterns
                image_patterns = [
                    f"{redis_key_prefix}:images:{sender}:*",  # Any sub-keys
                    f"{redis_key_prefix}:image_*:{sender}",  # Alternative naming
                    f"{redis_key_prefix}:collection:{sender}:*",  # Collection metadata
                    f"{redis_key_prefix}:temp_images:{sender}:*",  # Temporary image data
                    f"{redis_key_prefix}:processing:{sender}:*",  # Processing status
                ]

                for pattern in image_patterns:
                    try:
                        keys = await client.keys(pattern)
                        if keys:
                            deleted_count = await client.delete(*keys)
                            if deleted_count > 0:
                                cleared_keys.extend(keys)
                                self._logger.debug(
                                    f"Cleared {deleted_count} keys matching pattern '{pattern}' for {sender}"
                                )
                    except Exception as pattern_error:
                        self._logger.warning(
                            f"Error clearing pattern '{pattern}' for {sender}: {str(pattern_error)}"
                        )

                # 3. Clear any other keys that might contain image data
                general_patterns = [
                    f"{redis_key_prefix}:*:{sender}",  # Any wls-assistant keys for this sender
                ]

                for pattern in general_patterns:
                    try:
                        keys = await client.keys(pattern)
                        if keys:
                            # Filter out keys we've already cleared to avoid double-deletion
                            remaining_keys = [k for k in keys if k not in cleared_keys]
                            if remaining_keys:
                                deleted_count = await client.delete(*remaining_keys)
                                if deleted_count > 0:
                                    cleared_keys.extend(remaining_keys)
                                    self._logger.debug(
                                        f"Cleared {deleted_count} additional keys for {sender}"
                                    )
                    except Exception as general_error:
                        self._logger.warning(
                            f"Error clearing general pattern '{pattern}' for {sender}: {str(general_error)}"
                        )

                # 4. Clear any hash fields that might contain image metadata
                try:
                    # Check if there are any hash structures containing image data
                    hash_patterns = [
                        f"{redis_key_prefix}:metadata:{sender}",
                        f"{redis_key_prefix}:user_data:{sender}",
                    ]

                    for hash_key in hash_patterns:
                        if await client.exists(hash_key):
                            # Clear specific hash fields related to images
                            image_fields = [
                                "images",
                                "image_count",
                                "last_image",
                                "collection_status",
                            ]
                            for field in image_fields:
                                await client.hdel(hash_key, field)
                            self._logger.debug(
                                f"Cleared image-related hash fields from {hash_key} for {sender}"
                            )

                except Exception as hash_error:
                    self._logger.warning(
                        f"Error clearing hash fields for {sender}: {str(hash_error)}"
                    )

                total_cleared = len(cleared_keys)
                if total_cleared > 0:
                    self._logger.info(
                        f"Comprehensive image collection cleanup completed for {sender}: cleared {total_cleared} keys"
                    )
                else:
                    self._logger.debug(
                        f"No image collection keys found to clear for {sender}"
                    )

                return True

        except Exception as e:
            self._logger.error(
                f"Error in comprehensive image collection cleanup for {sender}: {str(e)}"
            )
            return False

    def deduplicate_media_urls(self, urls: List[str]) -> List[str]:
        """
        Deduplicate media URLs, removing empty/None values and duplicates.
        This is a utility function to ensure consistent URL handling across the system.
        """
        if not urls:
            return []

        unique_urls = []
        seen_urls = set()

        for url in urls:
            if url and url.strip():  # Check for non-empty, non-whitespace URLs
                if url not in seen_urls:
                    unique_urls.append(url)
                    seen_urls.add(url)

        return unique_urls

    def log_media_urls_state(
        self, sender: str, context: str, urls: List[str], unique_urls: List[str] = None
    ):
        """
        Helper function to log the state of media URLs for debugging purposes.
        """
        if unique_urls is None:
            unique_urls = self.deduplicate_media_urls(urls)

        if len(urls) != len(unique_urls):
            self._logger.info(
                f"[{context}] {sender}: Deduplicated URLs {len(urls)} -> {len(unique_urls)}"
            )
            if len(urls) > 10:  # Only show first few URLs if there are many
                self._logger.info(f"[{context}] {sender}: First 5 URLs: {urls[:5]}")
                self._logger.info(
                    f"[{context}] {sender}: Duplicates detected and removed"
                )
        else:
            self._logger.debug(
                f"[{context}] {sender}: No duplicates in {len(urls)} URLs"
            )

        return unique_urls

    async def get_multiple_collections(
        self, senders: List[str]
    ) -> Dict[str, Optional[Dict]]:
        """Get multiple image collections in a single batch operation"""
        try:
            keys = []
            for sender in senders:
                if self._config is None:
                    keys.append(f"{redis_key_prefix}:images:{sender}")
                else:
                    keys.append(self._config.get_images_key(sender))

            async with self.get_client() as client:
                pipe = client.pipeline()
                for key in keys:
                    pipe.get(key)
                    pipe.ttl(key)  # Also get TTL for each key
                results = await pipe.execute()

                collections = {}
                for i, sender in enumerate(senders):
                    data_index = i * 2
                    ttl_index = i * 2 + 1

                    if results[data_index]:
                        collection = json.loads(results[data_index])
                        # Add TTL information
                        if results[ttl_index] > 0:
                            collection["_ttl_seconds"] = results[ttl_index]
                        collections[sender] = collection
                    else:
                        collections[sender] = None

                return collections

        except Exception as e:
            self._logger.error(f"Error getting multiple collections: {str(e)}")
            return {sender: None for sender in senders}

    # --- Helper Methods ---

    def _handle_error(self, error_message: str) -> None:
        """Handle Redis errors"""
        self._last_error = error_message
        self._last_error_time = get_this_moment()
        self._error_count += 1

        # Open circuit breaker if too many errors
        if self._error_count >= 5:
            self._circuit_open = True
            self._in_memory_mode = True
            logger.warning("Circuit breaker opened due to too many Redis errors")

        logger.error(error_message)

    def _get_in_memory(self, key: str) -> Any:
        """Get value from in-memory store"""
        # Check if key exists
        if key not in self._in_memory_data:
            return None

        # Check if key has expired
        if key in self._in_memory_ttl and self._in_memory_ttl[key] < get_this_moment():
            # Remove expired key
            del self._in_memory_data[key]
            del self._in_memory_ttl[key]
            return None

        return self._in_memory_data[key]

    async def _set_in_memory(
        self, key: str, value: Any, ex: Optional[int] = None
    ) -> bool:
        """Set value in in-memory store"""
        self._in_memory_data[key] = value

        if ex:
            self._in_memory_ttl[key] = get_this_moment() + timedelta(seconds=ex)

        return True

    async def _delete_in_memory(self, key: str) -> int:
        """Delete key from in-memory store"""
        if key in self._in_memory_data:
            del self._in_memory_data[key]
            if key in self._in_memory_ttl:
                del self._in_memory_ttl[key]
            return 1
        return 0

    async def _keys_in_memory(self, pattern: str) -> List[str]:
        """Get keys matching a pattern from in-memory store"""
        import re

        # Convert Redis pattern to regex
        regex_pattern = pattern.replace("*", ".*")
        regex = re.compile(regex_pattern)
        return [k for k in self._in_memory_data.keys() if regex.match(k)]

    async def _ttl_in_memory(self, key: str) -> int:
        """Get TTL for a key from in-memory store"""
        if key not in self._in_memory_data:
            return -2  # Key doesn't exist
        if key not in self._in_memory_ttl:
            return -1  # No expiration
        ttl = (self._in_memory_ttl[key] - get_this_moment()).total_seconds()
        return max(0, int(ttl))

    async def _expire_in_memory(self, key: str, ex: int) -> bool:
        """Set expiration for a key in in-memory store"""
        if key in self._in_memory_data:
            self._in_memory_ttl[key] = get_this_moment() + timedelta(seconds=ex)
            return True
        return False

    async def _handle_image_collection(
        self,
        state: Dict[str, Any],
        sender: str,
        media_url: str,
        is_worker_request: bool,
    ) -> Dict[str, Any]:
        """Handle the actual image collection process"""

        try:
            # Add image to collection
            image_count = await self.add_image_to_collection(sender, media_url)

            if image_count == 0:
                raise ImageCollectionError("Failed to add image to collection")

            logger.info(
                f"Added image to collection for {sender}. Total images: {image_count}"
            )

            # Get collection timeout (configurable per user or default)
            timeout_seconds = state.get("collection_timeout_seconds", 30)

            # Check if collection is ready for processing
            collection_ready = await self.is_collection_ready_for_processing(
                sender, timeout_seconds=timeout_seconds
            )

            logger.info(
                f"Collection ready check: ready={collection_ready}, timeout={timeout_seconds}s"
            )

            if not collection_ready:
                # Update state to reflect active collection
                state["status"] = "collecting_images"
                state["image_collection_active"] = True
                state["image_collection_processed"] = False
                state["image_count"] = image_count
                state["collected_image_count"] = image_count

                # Generate appropriate response message
                if is_worker_request:
                    if image_count == 1:
                        response_message = (
                            f"📸 First image received for worker registration"
                        )
                    else:
                        response_message = (
                            f"📸 Image {image_count} received for worker registration"
                        )
                else:
                    response_message = f"📸 Image {image_count} received"

                # Add collection guidance
                if image_count == 1:
                    response_message += (
                        f".\n\n📋 Send more worker card images if you have multiple workers, "
                        f"or wait {timeout_seconds} seconds for automatic processing.\n\n"
                        f"💡 Tip: You can send up to 10 images at once for batch processing."
                        f"\n\n💬 Type 'done' to finish collection immediately."
                    )
                else:
                    response_message += (
                        f".\n\n⏳ Waiting {timeout_seconds} seconds for more images or processing will start automatically..."
                        f"\n\n💬 Type 'done' to finish collection immediately."
                    )

                # Update state
                state["action_result"] = response_message

                # Save state for persistence
                asyncio.create_task(save_state(sender, state))

                logger.info(
                    f"Collection in progress for {sender}: {image_count} images, timeout: {timeout_seconds}s"
                )
                return state
            else:
                # Collection is ready, process all images
                return await _handle_collection_complete(state, sender)

        except Exception as e:
            logger.error(f"Error in image collection handling: {str(e)}", exc_info=True)
            raise ImageCollectionError(f"Collection handling failed: {str(e)}")

    async def is_collection_ready_for_processing(
        self, sender: str, timeout_seconds: float = 30
    ) -> bool:
        """
        Check if the image collection is ready for processing.
        Ready if: last update was more than timeout_seconds ago.
        """
        try:
            logger.info(f"is_collection_ready_for_processing called for {sender}")
            collection = await self.get_image_collection(sender)
            logging.info(
                f"collection in is_collection_ready_for_processing in redis_manager: {collection}"
            )
            if not collection or not collection.get("images"):
                logger.info(f"No collection or images found for {sender}")
                return False

            last_updated_str = collection.get("last_updated")
            if not last_updated_str:
                logger.info(
                    f"No last_updated timestamp found, assuming collection is ready"
                )
                return True

            # Parse the ISO format datetime
            last_updated = datetime.fromisoformat(last_updated_str)

            # Ensure both datetimes have timezone info for comparison
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=HK_TZ)

            # Get current time with timezone
            now = get_this_moment() # in HK timezone


            # Calculate time difference
            time_since_update = now - last_updated

            # Convert timeout_seconds to timedelta for proper comparison
            timeout_delta = timedelta(seconds=timeout_seconds)

            # Check if enough time has passed
            is_ready = time_since_update >= timeout_delta

            logging.info(
                f"Collection readiness check for {sender}: "
                f"{len(collection['images'])} images, "
                f"last updated {time_since_update.total_seconds():.1f}s ago, "
                f"timeout: {timeout_seconds}s, "
                f"ready: {is_ready}"
            )

            return is_ready

        except Exception as e:
            logging.error(
                f"Error checking collection readiness for {sender}: {str(e)}",
                exc_info=True,
            )
            return False

    async def update_collection_original_body(
        self, sender: str, original_body: str
    ) -> bool:
        """Update the original body in the user's image collection"""
        try:
            if not original_body:
                logger.warning(f"Empty original body provided for {sender}")
                return False

            if self._config is None:
                key = f"{redis_key_prefix}:images:{sender}"
                default_ttl = 600  # Default 10 minutes if config is None
            else:
                key = self._config.get_images_key(sender)
                default_ttl = self._config.image_collection_ttl

            async with self.get_client() as client:
                # Get existing collection
                collection_data = await client.get(key)
                if not collection_data:
                    logger.info(
                        f"No collection found for {sender}, creating new one with original body"
                    )
                    # Create a new collection with the original body
                    collection = {
                        "images": [],
                        "created_at": get_this_moment().isoformat(),
                        "last_updated": get_this_moment().isoformat(),
                        "sender": sender,
                        "version": "1.0",
                        "original_body": original_body,
                    }
                else:
                    collection = json.loads(collection_data)
                    # Only update if the new body contains project info or the existing one doesn't
                    existing_body = collection.get("original_body", "")
                    if (
                        not existing_body
                        or "project" in original_body.lower()
                        or "工程" in original_body
                        or "add worker" in original_body.lower()
                    ):
                        collection["original_body"] = original_body
                        logger.info(
                            f"Updated original body in collection for {sender}: {original_body}"
                        )
                    else:
                        logger.info(f"Keeping existing original body: {existing_body}")

                collection["last_updated"] = get_this_moment().isoformat()

                # Get TTL of existing key
                ttl = await client.ttl(key)
                if ttl < 0:  # Key doesn't exist or no TTL
                    ttl = default_ttl

                # Save back to Redis with TTL
                await client.setex(
                    key, ttl, json.dumps(collection, default=self._custom_encoder)
                )

                logger.info(f"Saved collection with original body for {sender}")
                return True

        except Exception as e:
            logger.error(f"Error updating original body for {sender}: {str(e)}")
            return False


# Global Redis manager instance
redis_manager = RedisManager()


# Convenience functions
async def load_previous_state(sender: str) -> Optional[Dict[str, Any]]:
    """Load previous conversation state for a sender"""
    return await redis_manager.load_state(sender)


async def save_state(sender: str, state: Dict[str, Any]) -> bool:
    """Save conversation state for a sender"""
    return await redis_manager.save_state(sender, state)


async def clear_state(sender: str) -> int:
    """Clear conversation state for a sender"""
    return await redis_manager.clear_state(sender)


async def add_image_to_collection(sender: str, image_url: str, body: str = "") -> bool:
    """Add image to collection for a sender"""
    return await redis_manager.add_image_to_collection(sender, image_url, body)


async def get_image_collection(sender: str) -> List[Dict[str, Any]]:
    """Get image collection for a sender"""
    return await redis_manager.get_image_collection(sender)


async def clear_image_collection(sender: str) -> int:
    """Clear image collection for a sender"""
    return await redis_manager.clear_image_collection(sender)


async def batch_get_collections(senders: List[str]):
    """Get multiple collections efficiently"""
    return await redis_manager.get_multiple_collections(senders)


async def is_collection_ready_for_processing(sender: str, timeout_seconds: float = 30):
    """Check if collection is ready for processing (backward compatibility)"""
    return await redis_manager.is_collection_ready_for_processing(
        sender, timeout_seconds
    )


# Convenience function
async def update_collection_original_body(sender: str, original_body: str) -> bool:
    """Update the original body in the user's image collection"""
    return await redis_manager.update_collection_original_body(sender, original_body)


def _continue_with_normal_flow(state: Dict[str, Any]) -> Dict[str, Any]:
    """Continue with normal flow by setting appropriate status"""
    # Check if we have media URLs
    has_media = bool(state.get("media_urls"))

    # Preserve original body if it exists
    original_body = state.get("original_body", "")
    if original_body:
        logger.info(f"Preserving original body in normal flow: {original_body}")

        # If the current message doesn't have a body but we have an original body with project info,
        # use the original body for processing
        if state.get("messages") and len(state["messages"]) > 0:
            current_body = state["messages"][-1]["content"].get("Body", "").strip()
            if not current_body and original_body:
                state["messages"][-1]["content"]["Body"] = original_body
                logger.info(f"Updated message body with original body: {original_body}")

    # Check if image collection is already processed
    if state.get("image_collection_processed", False):
        # Collection is already processed, proceed to intent classification
        state["status"] = "await_intent"
        state["image_collection_active"] = False
        logger.info(
            "Image collection already processed, proceeding to intent classification"
        )
        return state

    # If we have media but aren't in collecting state and collection isn't processed, set it
    if (
        has_media
        and state.get("status") != "collecting_images"
        and not state.get("image_collection_processed", False)
    ):
        state["status"] = "collecting_images"
        state["image_collection_active"] = True
        logger.info("Setting status to collecting_images due to media URLs in state")
        return state

    # Otherwise proceed with normal flow
    state["status"] = "await_intent"
    logger.info("Continuing with normal flow, setting status to await_intent")
    return state


# Helper function to sync Redis collection with state
async def sync_collection_to_state(
    sender: str, state: Dict[str, Any]
) -> Dict[str, Any]:
    """Sync Redis collection to state"""
    try:
        collection = await get_image_collection(sender)
        if collection and collection.get("images"):
            state["media_urls"] = collection["images"]
            state["image_count"] = len(collection["images"])
            state["collected_image_count"] = len(collection["images"])
            logger.info(
                f"Synced {len(collection['images'])} images from Redis to state"
            )
        return state
    except Exception as e:
        logger.error(f"Error syncing collection to state: {str(e)}")
        return state


async def _handle_collection_complete(
    state: Dict[str, Any], sender: str
) -> Dict[str, Any]:
    """Handle when collection is complete and ready for processing"""

    try:
        # Get the complete collection
        collection = await get_image_collection(sender)
        if not collection or not collection.get("images"):
            logger.warning("Collection marked as ready but no images found")
            return _continue_with_normal_flow(state)

        all_images = collection["images"]
        collection_created = collection.get("created_at")

        logger.info(
            f"Processing complete collection for {sender}: {len(all_images)} images, "
            f"created: {collection_created}"
        )

        # Validate collection
        if len(all_images) > 10:  # Reasonable limit
            logger.warning(f"Too many images in collection: {len(all_images)}")
            state["action_result"] = (
                f"⚠️ Too many images ({len(all_images)}). Maximum 10 images allowed. "
                "Please start a new collection."
            )
            await clear_image_collection(sender)
            return state

        # Ensure media_urls are unique
        url_dict = {}
        for url in all_images:
            url_dict[url] = True
        unique_images = list(url_dict.keys())

        if len(unique_images) != len(all_images):
            logger.info(
                f"Deduplicated images: {len(all_images)} -> {len(unique_images)}"
            )

        # Prepare state for main workflow - CRITICAL: Transfer images to state
        # This ensures the images are available for processing
        state["media_urls"] = unique_images  # Use deduplicated images
        state["image_collection_processed"] = True
        state["collected_image_count"] = len(unique_images)
        state["image_collection_active"] = True
        state["image_count"] = len(unique_images)
        state["status"] = "await_intent"  # Move to intent classification

        logger.info(
            f"Transferred {len(unique_images)} images from Redis collection to state['media_urls']"
        )

        # Get original body from collection
        collection_body = collection.get("original_body", "")
        if collection_body:
            state["original_body"] = collection_body
            logger.info(f"Using original body from collection: {collection_body}")

        # Update message body to include project info for downstream processing
        # This helps the intent classifier recognize this as a worker registration
        if state.get("messages") and len(state["messages"]) > 0:
            # Use original_body if available, otherwise use current body
            original_body = state.get("original_body", "")
            current_body = (
                state["messages"][-1]["content"].get("Body", "").lower().strip()
            )

            if original_body and (
                "project" in original_body.lower() or "工程" in original_body
            ):
                # Use the original body with project info
                state["messages"][-1]["content"]["Body"] = original_body
                logger.info(f"Using original body with project info: {original_body}")
            elif not current_body or "worker" not in current_body:
                # If no project info and no worker keyword, use a default
                state["messages"][-1]["content"]["Body"] = "add workers"
                logger.info(f"Updated message body to: add workers")

        # Clean up collection
        await clear_image_collection(sender)

        # Add processing confirmation to action_result
        state["action_result"] = (
            f"✅ Processing {len(unique_images)} worker card image(s)"
            + ". Please wait for the results..."
        )

        logger.info(
            f"Image collection complete for {sender}. Processing {len(unique_images)} images."
        )
        return state

    except Exception as e:
        logger.error(f"Error handling collection completion: {str(e)}", exc_info=True)
        await clear_image_collection(sender)  # Clean up on error
        raise ImageCollectionError(f"Failed to process complete collection: {str(e)}")


def _handle_collection_in_progress(
    state: Dict[str, Any],
    sender: str,
    image_count: int,
    timeout_seconds: int,
    is_worker_request: bool,
) -> Dict[str, Any]:
    """Handle when collection is still in progress"""

    # Generate appropriate response message
    if is_worker_request:
        if image_count == 1:
            response_message = f"📸 First image received for worker registration"
        else:
            response_message = (
                f"📸 Image {image_count} received for worker registration"
            )
    else:
        response_message = f"📸 Image {image_count} received"

    # Add collection guidance
    if image_count == 1:
        response_message += (
            f".\n\n📋 Send more worker card images if you have multiple workers, "
            f"or wait {timeout_seconds} seconds for automatic processing.\n\n"
            f"💡 Tip: You can send up to 10 images at once for batch processing."
        )
    else:
        response_message += f".\n\n⏳ Waiting {timeout_seconds} seconds for more images or processing will start automatically..."

    # Update state
    state["status"] = "collecting_images"
    state["action_result"] = response_message
    state["image_collection_active"] = True
    state["image_count"] = len(state["media_urls"])

    # Save state for persistence
    asyncio.create_task(save_state(sender, state))

    logger.info(
        f"Collection in progress for {sender}: {image_count} images, timeout: {timeout_seconds}seconds"
    )
    return state
