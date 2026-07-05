"""Application configuration via environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


# Load .env values into the environment before Pydantic reads settings.
# This makes `Settings()` support values defined in a project-root .env file.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class Settings(BaseSettings):
    """Global application settings loaded from env vars."""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Executor — pluggable backends
    EXECUTOR_BACKEND: str = "docker"  # "docker" | "kubernetes" | "hybrid" | "subprocess"
    EXECUTOR_IMAGE: str = "thinkdome-executor:latest"

    # Docker backend settings
    DOCKER_HOST: str = "unix:///var/run/docker.sock"  # Use tcp://localhost:2376 for DinD sidecar
    DOCKER_TLS_VERIFY: bool = False                    # True when using DinD with mutual TLS
    DOCKER_CERT_PATH: Optional[str] = None             # Path to TLS certs for DinD

    # Kubernetes backend settings
    K8S_NAMESPACE: str = "thinkdome-sandboxes"
    K8S_RUNTIME_CLASS: str = "gvisor"                  # gvisor | kata | runc
    K8S_IN_CLUSTER: bool = True                        # Use in-cluster config

    # Execution limits
    MAX_EXEC_TIMEOUT_MS: int = 10000
    CPU_TIME_LIMIT_SEC: int = 5
    MEMORY_LIMIT_MB: int = 128
    MAX_OUTPUT_BYTES: int = 1_048_576  # 1 MB

    # GPU support
    GPU_ENABLED: bool = False
    GPU_MAX_PER_SANDBOX: int = 1
    GPU_DEVICE_TYPE: str = "nvidia.com/gpu"  # K8s resource name

    # File management
    MAX_FILE_SIZE_MB: int = 10
    FILE_STORAGE_DIR: str = "./storage"

    # Security
    API_KEY: Optional[str] = None  # Optional: set to enable API key auth

    # ── Production Infrastructure ──
    DATABASE_URL: str = "postgresql://thinkdome:thinkdome@localhost:5432/thinkdome"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── OpenTelemetry ──
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "thinkdome-api"

    # ── Idle Detection ──
    IDLE_TIMEOUT_SEC: int = 600  # Auto-terminate sandboxes idle > 10 min

    # Search Tool Settings
    SEARCH_PROVIDER: str = "duckduckgo"
    TAVILY_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None
    SEARCH_RATE_LIMIT: int = 30
    SEARCH_MAX_RESULTS: int = 10

    # SMTP Email Settings
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None        # Default sender address
    SMTP_USE_TLS: bool = True

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # ── Pool Manager Settings ──
    POOL_MIN_WARM: int = 3              # Minimum pre-warmed containers
    POOL_MAX_SIZE: int = 50             # Maximum pool capacity
    POOL_EVICTION_GRACE_SEC: int = 30   # Lazy eviction grace period (seconds)
    POOL_DEMAND_WINDOW_SEC: int = 60    # Demand estimation rolling window (seconds)
    POOL_ENABLED: bool = True           # Enable/disable pool manager

    # ── Monitor Settings ──
    MONITOR_POLL_INTERVAL_SEC: float = 2.0    # Metrics collection interval
    MONITOR_RETENTION_SEC: int = 300          # Metrics history retention (5 min)
    MONITOR_ALERT_COOLDOWN_SEC: int = 60      # Alert dedup cooldown

    # ── Credential Vault Settings ──
    VAULT_MASTER_KEY: Optional[str] = None    # Fernet key for vault encryption

    model_config = {"env_prefix": "", "case_sensitive": True}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
