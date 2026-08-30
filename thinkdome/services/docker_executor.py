"""Standalone entrypoint for Docker Executor Control-Plane Service (DIND-002).

Usage:
    python -m thinkdome.services.docker_executor
"""

from __future__ import annotations

import logging
import os
import uvicorn

from thinkdome.core.config import get_settings
from thinkdome.sandbox.executors.docker.service import get_executor_app

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    settings = get_settings()
    host = os.environ.get("EXECUTOR_CONTROL_HOST", "0.0.0.0")
    port = int(os.environ.get("EXECUTOR_CONTROL_PORT", "8200"))

    logger.info(f"🚀 Starting Docker Executor Control-Plane Service on {host}:{port}...")
    app = get_executor_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")
