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

    # Executor
    EXECUTOR_BACKEND: str = "docker"  # "docker" | "subprocess" (for dev)
    EXECUTOR_IMAGE: str = "thinkdome-executor:latest"

    # Execution limits
    MAX_EXEC_TIMEOUT_MS: int = 10000
    CPU_TIME_LIMIT_SEC: int = 5
    MEMORY_LIMIT_MB: int = 128
    MAX_OUTPUT_BYTES: int = 1_048_576  # 1 MB

    # File management
    MAX_FILE_SIZE_MB: int = 10
    FILE_STORAGE_DIR: str = "./storage"

    # Security
    API_KEY: Optional[str] = None  # Optional: set to enable API key auth

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

    model_config = {"env_prefix": "", "case_sensitive": True}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
