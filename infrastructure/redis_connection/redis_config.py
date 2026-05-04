"""
Redis Configuration Management for WLS Assistant
Handles Redis configuration, environment variables, and connection settings.
Enhanced version with better Docker networking support and fallback mechanisms.
"""

import logging
import os
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RedisMode(str, Enum):
    """Redis deployment modes"""

    REDIS_DEV = "development"  # local development
    REDIS_PROD = "production"  # production deployment

    @classmethod
    def _missing_(cls, value):
        """Handle missing values gracefully"""
        # Map old values to new ones
        if value == "local":
            return cls.REDIS_DEV
        if value == "docker":
            return cls.REDIS_PROD
        return None


@dataclass
class RedisConfig:
    """Redis configuration with environment-based defaults"""

    # Connection settings
    host: str = field(default_factory=lambda: os.getenv("REDIS_HOST") or "localhost")
    port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", 6379)))
    db: int = field(default_factory=lambda: int(os.getenv("REDIS_DB", 0)))

    # Connection pool settings
    max_connections: int = field(
        default_factory=lambda: int(os.getenv("REDIS_MAX_CONNECTIONS", 20))
    )
    min_connections: int = field(
        default_factory=lambda: int(os.getenv("REDIS_MIN_CONNECTIONS", 1))
    )
    socket_timeout: int = field(
        default_factory=lambda: int(os.getenv("REDIS_SOCKET_TIMEOUT", 30))
    )
    socket_connect_timeout: int = field(
        default_factory=lambda: int(os.getenv("REDIS_CONNECT_TIMEOUT", 10))
    )
    socket_keepalive: bool = field(
        default_factory=lambda: os.getenv("REDIS_SOCKET_KEEPALIVE", "true").lower()
        == "true"
    )
    socket_keepalive_options: Dict[str, int] = field(default_factory=dict)

    # Retry and reliability settings
    retry_on_timeout: bool = field(
        default_factory=lambda: os.getenv("REDIS_RETRY_ON_TIMEOUT", "true").lower()
        == "true"
    )
    retry_on_error: list = field(default_factory=list)
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("REDIS_MAX_RETRIES", 5))
    )
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv("REDIS_RETRY_DELAY", 0.5))
    )

    # SSL/TLS settings
    ssl: bool = field(
        default_factory=lambda: os.getenv("REDIS_SSL", "false").lower() == "true"
    )
    ssl_certfile: Optional[str] = field(
        default_factory=lambda: os.getenv("REDIS_SSL_CERTFILE")
    )
    ssl_keyfile: Optional[str] = field(
        default_factory=lambda: os.getenv("REDIS_SSL_KEYFILE")
    )
    ssl_ca_certs: Optional[str] = field(
        default_factory=lambda: os.getenv("REDIS_SSL_CA_CERTS")
    )
    ssl_check_hostname: bool = field(
        default_factory=lambda: os.getenv("REDIS_SSL_CHECK_HOSTNAME", "true").lower()
        == "true"
    )

    # Performance settings
    decode_responses: bool = field(
        default_factory=lambda: os.getenv("REDIS_DECODE_RESPONSES", "true").lower()
        == "true"
    )
    encoding: str = field(default_factory=lambda: os.getenv("REDIS_ENCODING", "utf-8"))

    # Application-specific settings
    key_prefix: str = field(
        default_factory=lambda: os.getenv("REDIS_KEY_PREFIX", "wls-assistant")
    )
    default_ttl: int = field(
        default_factory=lambda: int(os.getenv("REDIS_DEFAULT_TTL", 86400))
    )  # 24 hours
    image_collection_ttl: int = field(
        default_factory=lambda: int(os.getenv("REDIS_IMAGE_TTL", 600))
    )  # 10 minutes
    state_ttl: int = field(
        default_factory=lambda: int(os.getenv("REDIS_STATE_TTL", 86400))
    )  # 24 hours

    # Monitoring and health check settings
    health_check_interval: int = field(
        default_factory=lambda: int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", 30))
    )
    enable_monitoring: bool = field(
        default_factory=lambda: os.getenv("REDIS_ENABLE_MONITORING", "true").lower()
        == "true"
    )
    log_slow_queries: bool = field(
        default_factory=lambda: os.getenv("REDIS_LOG_SLOW_QUERIES", "true").lower()
        == "true"
    )
    slow_query_threshold: float = field(
        default_factory=lambda: float(os.getenv("REDIS_SLOW_QUERY_THRESHOLD", 0.1))
    )

    # Deployment mode
    mode: RedisMode = field(
        default_factory=lambda: RedisMode(os.getenv("REDIS_MODE", "development"))
    )

    # Circuit breaker settings
    circuit_breaker_enabled: bool = field(
        default_factory=lambda: os.getenv(
            "REDIS_CIRCUIT_BREAKER_ENABLED", "true"
        ).lower()
        == "true"
    )
    circuit_breaker_threshold: int = field(
        default_factory=lambda: int(os.getenv("REDIS_CIRCUIT_BREAKER_THRESHOLD", 5))
    )
    circuit_breaker_timeout: int = field(
        default_factory=lambda: int(os.getenv("REDIS_CIRCUIT_BREAKER_TIMEOUT", 30))
    )

    # Fallback hosts for Docker networking issues
    fallback_hosts: List[str] = field(
        default_factory=lambda: [
            "redis",  # Docker service name
            "172.18.0.2",  # Actual Redis container IP (from docker inspect)
            "redis-container",  # Container name
            "localhost",
            "127.0.0.1",
        ]
    )

    def __post_init__(self):
        """Post-initialization validation and setup"""
        self._validate_config()
        self._setup_mode_specific_settings()
        self._resolve_optimal_host()

    def _validate_config(self):
        """Validate configuration values"""
        if self.db < 0 or self.db > 15:
            raise ValueError(f"Invalid Redis database: {self.db}")

        if self.max_connections < self.min_connections:
            raise ValueError("max_connections must be >= min_connections")

        if self.socket_timeout <= 0:
            raise ValueError("socket_timeout must be positive")

        if self.default_ttl <= 0:
            raise ValueError("default_ttl must be positive")

        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")

        if self.retry_delay <= 0:
            raise ValueError("retry_delay must be positive")

        if self.circuit_breaker_threshold <= 0:
            raise ValueError("circuit_breaker_threshold must be positive")

        if self.circuit_breaker_timeout <= 0:
            raise ValueError("circuit_breaker_timeout must be positive")

        # Validate SSL configuration
        if self.ssl:
            if self.ssl_certfile and not os.path.exists(self.ssl_certfile):
                logging.warning(f"SSL certfile not found: {self.ssl_certfile}")
            if self.ssl_keyfile and not os.path.exists(self.ssl_keyfile):
                logging.warning(f"SSL keyfile not found: {self.ssl_keyfile}")
            if self.ssl_ca_certs and not os.path.exists(self.ssl_ca_certs):
                logging.warning(f"SSL CA certs not found: {self.ssl_ca_certs}")

    def _setup_mode_specific_settings(self):
        """Setup mode-specific configuration"""
        if self.mode == RedisMode.REDIS_PROD:
            # Docker-specific settings
            # Check if host is 'localhost' without port
            if self.host == "localhost" or self.host == "127.0.0.1":
                self.host = os.getenv("REDIS_DOCKER_HOST", "redis")
                self.port = os.getenv("REDIS_PORT", 6379)
            # Add docker-specific fallback hosts
            self.fallback_hosts = [
                "redis",  # Docker service name
                "172.18.0.2",  # Actual Redis container IP (from docker inspect)
                "redis-container",  # Container name
                "172.17.0.1",  # Docker host IP
                "host.docker.internal",
                "127.0.0.1",
            ]

        elif self.mode == RedisMode.REDIS_DEV:
            # Local development settings - prefer 127.0.0.1 over localhost
            if self.host == "localhost":
                self.host = "127.0.0.1"
                self.port = 6379
            elif self.host == "127.0.0.1" and ":" not in self.host:
                self.host = "127.0.0.1"
                self.port = 6379

            # Increase timeouts for local development
            self.socket_timeout = max(self.socket_timeout, 10)
            self.socket_connect_timeout = max(self.socket_connect_timeout, 5)

    def _resolve_optimal_host(self):
        """Resolve the optimal host for connection, with fallback mechanisms"""
        logger = logging.getLogger(__name__)

        # If host is an IP address, skip resolution
        if self._is_ip_address(self.host):
            logger.debug(f"Using IP address directly: {self.host}")
            return

        # Try to resolve the configured host first
        if self._can_resolve_host(self.host):
            logger.debug(f"Successfully resolved configured host: {self.host}")
            return

        # If configured host fails, try fallback hosts
        logger.warning(f"Could not resolve configured Redis host: {self.host}")

        for fallback_host in self.fallback_hosts:
            if fallback_host == self.host:
                continue  # Skip the already failed host

            if self._can_connect_to_host(fallback_host):
                logger.warning(
                    f"Using fallback Redis host: {fallback_host} (was: {self.host})"
                )
                self.host = fallback_host
                return

        # If all fallbacks fail, log warning but keep original host
        logger.error(
            f"All Redis host resolution attempts failed. Keeping original host: {self.host}"
        )
        logger.error(
            "This will likely cause connection failures. Check your Docker network configuration."
        )

    def _is_ip_address(self, host: str) -> bool:
        """Check if host is an IP address"""
        try:
            socket.inet_aton(host)
            return True
        except socket.error:
            return False

    def _can_resolve_host(self, host: str) -> bool:
        """Check if a hostname can be resolved"""
        try:
            socket.gethostbyname(host)
            return True
        except socket.gaierror:
            return False

    def _can_connect_to_host(self, host: str, timeout: int = 2) -> bool:
        """Check if we can connect to a host on the Redis port"""
        try:
            # Use socket.create_connection which handles host:port format correctly
            host_parts = host.split(":")
            if len(host_parts) == 2:
                hostname = host_parts[0]
                try:
                    port = int(host_parts[1])
                except ValueError:
                    # Default to standard Redis port if port is not a valid integer
                    port = 6379
            else:
                hostname = host
                port = 6379  # Default Redis port

            sock = socket.create_connection((hostname, port), timeout=timeout)
            sock.close()
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Connection test error for {host}: {e}")
            return False

    async def test_connection(self) -> bool:
        """Test Redis connection asynchronously"""
        try:
            import redis.asyncio as redis

            client = redis.Redis(**self.get_connection_kwargs())
            await client.ping()
            await client.close()
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Redis connection test failed: {e}")
            return False

    def test_connection_sync(self) -> bool:
        """Test Redis connection synchronously (for non-async contexts)"""
        return self._can_connect_to_host(self.host, timeout=5)

    def get_connection_kwargs(self) -> Dict[str, Any]:
        """Get connection parameters for Redis client"""
        # Use the host string directly without parsing it
        host, port = (self.host.split(":") + ["6379"])[:2]
        # Redis Python client will handle the host:port format correctly
        kwargs = {
            "host": host,
            "port": int(port),
            "db": self.db,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "socket_keepalive": self.socket_keepalive,
            "retry_on_timeout": self.retry_on_timeout,
            "decode_responses": self.decode_responses,
            "encoding": self.encoding,
        }

        if self.ssl:
            kwargs["ssl"] = True
            if self.ssl_certfile:
                kwargs["ssl_certfile"] = self.ssl_certfile
            if self.ssl_keyfile:
                kwargs["ssl_keyfile"] = self.ssl_keyfile
            if self.ssl_ca_certs:
                kwargs["ssl_ca_certs"] = self.ssl_ca_certs
            kwargs["ssl_check_hostname"] = self.ssl_check_hostname

        if self.socket_keepalive_options:
            kwargs["socket_keepalive_options"] = self.socket_keepalive_options

        return kwargs

    def get_pool_kwargs(self) -> Dict[str, Any]:
        """Get connection pool parameters"""
        return {
            "max_connections": self.max_connections,
            "retry_on_timeout": self.retry_on_timeout,
            "retry_on_error": self.retry_on_error,
            **self.get_connection_kwargs(),
        }

    def get_key(self, key_type: str, identifier: str) -> str:
        """Generate a properly namespaced Redis key"""
        return f"{self.key_prefix}:{key_type}:{identifier}"

    def get_state_key(self, sender: str) -> str:
        """Get state key for a sender"""
        return self.get_key("state", sender)

    def get_images_key(self, sender: str) -> str:
        """Get image collection key for a sender"""
        return self.get_key("images", sender)

    def get_lock_key(self, resource: str) -> str:
        """Get lock key for a resource"""
        return self.get_key("lock", resource)

    def get_monitoring_key(self, metric: str) -> str:
        """Get monitoring key for a metric"""
        return self.get_key("monitor", metric)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for logging/debugging"""
        config_dict = {}
        for key, value in self.__dict__.items():
            if key.startswith("_"):  # Skip private attributes
                continue
            config_dict[key] = value
        return config_dict

    def get_connection_url(self) -> str:
        """Get Redis connection URL for display/logging"""
        protocol = "rediss" if self.ssl else "redis"
        auth = ""

        # Don't add port if it's already in the host string
        if ":" in self.host:
            return f"{protocol}://{auth}{self.host}:{self.port}/{self.db}"
        else:
            # Use default Redis port if not specified
            return f"{protocol}://{auth}{self.host}:{self.port}/{self.db}"


class RedisConfigManager:
    """Manages Redis configuration across different environments"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config: Optional[RedisConfig] = None
        self._environment_info: Dict[str, Any] = self._get_environment_info()

    def get_config(self, reload: bool = False) -> RedisConfig:
        """Get Redis configuration, optionally reloading from environment"""
        if self._config is None or reload:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> RedisConfig:
        """Load configuration from environment"""
        try:
            # Auto-detect environment
            environment = self._detect_environment()
            self.logger.info(f"Detected environment: {environment}")

            # Set environment-specific defaults
            self._set_environment_defaults(environment)

            config = RedisConfig()

            # Test connection and provide feedback
            if config.test_connection_sync():
                self.logger.info(f"Redis connection successful to {config.host}")
            else:
                self.logger.warning(f"Redis connection test failed for {config.host}")

            self.logger.info(
                f"Loaded Redis config for mode: {config.mode}, environment: {environment}"
            )
            self.logger.debug(f"Redis config: {config.to_dict()}")
            self.logger.debug(f"Redis connection URL: {config.get_connection_url()}")
            return config
        except Exception as e:
            self.logger.error(f"Failed to load Redis config: {str(e)}")
            raise

    def _detect_environment(self) -> str:
        """Auto-detect the current environment"""
        # Check explicit environment variable first
        if os.getenv("APP_ENV"):
            return os.getenv("APP_ENV").lower()
        if os.getenv("ENVIRONMENT"):
            return os.getenv("ENVIRONMENT").lower()

        # Check for Docker indicators
        if self._is_docker_environment():
            return "docker"

        # Check for production indicators
        if any(
            key in os.environ for key in ["PRODUCTION", "PROD", "RAILWAY_ENVIRONMENT"]
        ):
            return "production"

        # Default to development
        return "development"

    def _is_docker_environment(self) -> bool:
        """Check if running in Docker"""

        docker_indicators = [
            "CONTAINER",
            "DOCKER",
            "DOCKERIZED",
            "KUBERNETES_SERVICE_HOST",
            "HOSTNAME",
        ]

        if any(key in os.environ for key in docker_indicators):
            return True

        try:
            with open("/proc/1/cgroup", "r") as f:
                content = f.read()
                return "docker" in content or "containerd" in content
        except (FileNotFoundError, PermissionError):
            pass

        return False

    def _set_environment_defaults(self, environment: str):
        """Set environment-specific defaults"""
        if environment in ["production", "docker"]:
            if not os.getenv("REDIS_HOST"):
                os.environ["REDIS_HOST"] = "redis"
            if not os.getenv("REDIS_MODE"):
                os.environ["REDIS_MODE"] = "production"
            if not os.getenv("REDIS_DB"):
                os.environ["REDIS_DB"] = "0"
        else:
            if not os.getenv("REDIS_HOST"):
                os.environ["REDIS_HOST"] = "localhost"
            if not os.getenv("REDIS_MODE"):
                os.environ["REDIS_MODE"] = "development"
            if not os.getenv("REDIS_DB"):
                os.environ["REDIS_DB"] = "1"

    def validate_connection(self, config: RedisConfig) -> bool:
        """Validate that the configuration can establish a connection"""
        return config.test_connection_sync()

    def _get_environment_info(self) -> Dict[str, Any]:
        """Get information about the current environment"""
        environment = self._detect_environment()
        is_docker = self._is_docker_environment()

        return {
            "redis_mode": os.getenv("REDIS_MODE", "docker" if is_docker else "local"),
            "redis_host": os.getenv(
                "REDIS_HOST", "redis" if is_docker else "localhost"
            ),
            "redis_port": os.getenv("REDIS_PORT", "6379"),
            "redis_db": os.getenv(
                "REDIS_DB", "0" if environment in ["production", "docker"] else "1"
            ),
            "redis_ssl": os.getenv("REDIS_SSL", "false"),
            "environment": environment,
            "is_docker": is_docker,
            "hostname": socket.gethostname(),
            "container_id": os.getenv("HOSTNAME", "unknown"),
        }

    def get_environment_info(self) -> Dict[str, Any]:
        """Get information about the current environment"""
        return self._environment_info


config_manager = RedisConfigManager()


def get_redis_config() -> RedisConfig:
    """Get the current Redis configuration"""
    return config_manager.get_config()


def get_local_config() -> RedisConfig:
    """Get configuration for local development"""
    os.environ.update(
        {
            "REDIS_MODE": "development",
            "REDIS_HOST": "localhost:6379",
            "REDIS_SSL": "false",
        }
    )
    return RedisConfig()


def get_docker_config() -> RedisConfig:
    """Get configuration for Docker deployment"""
    os.environ.update(
        {
            "REDIS_MODE": "production",
            "REDIS_HOST": "redis",
            "REDIS_PORT": "6379",
            "REDIS_SSL": "false",
        }
    )
    return RedisConfig()


def get_production_config() -> RedisConfig:
    """Get configuration for production deployment"""
    os.environ.update(
        {"REDIS_MODE": "production", "REDIS_SSL": "true", "REDIS_MAX_CONNECTIONS": "10"}
    )
    return RedisConfig()


def detect_environment() -> RedisConfig:
    """Auto-detect environment and return appropriate configuration"""
    return config_manager.get_config()


async def diagnose_redis_connection():
    """Diagnose Redis connection issues and provide recommendations"""
    logger = logging.getLogger(__name__)
    config = get_redis_config()

    logger.info("=== Redis Connection Diagnosis ===")
    logger.info(f"Environment: {config_manager._get_environment_info()}")
    logger.info(f"Config: {config.to_dict()}")

    if await config.test_connection():
        logger.info(f"✅ Successfully connected to Redis at {config.host}")
    else:
        logger.error(f"❌ Failed to connect to Redis at {config.host}")

        logger.info("Testing fallback hosts...")
        for host in config.fallback_hosts:
            if config._can_connect_to_host(host):
                logger.info(f"✅ Fallback host {host} is reachable")
                logger.info(
                    f"💡 Recommendation: Set REDIS_HOST={host} in your environment"
                )
                break
            else:
                logger.warning(f"❌ Fallback host {host} is not reachable")

        logger.info("\n=== Recommendations ===")
        if config.mode == RedisMode.REDIS_PROD:
            logger.info("1. Ensure Redis container is running: docker ps | grep redis")
            logger.info("2. Check Docker network: docker network ls")
            logger.info("3. Verify both containers are on same network")
            logger.info(
                "4. Try using the actual Redis container IP: docker inspect redis-container | grep IPAddress"
            )
            logger.info(
                "5. Set REDIS_HOST=172.18.0.2:6379 (or the actual IP from step 4)"
            )
        else:
            logger.info("1. Ensure Redis server is running: redis-cli ping")
            logger.info("2. Check if Redis is listening on correct port")
            logger.info("3. Try: REDIS_HOST=127.0.0.1:6379")

    return "Diagnosis complete"
