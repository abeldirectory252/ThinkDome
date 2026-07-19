"""ThinkDome Framework & Application Server.

Integrates the multi-tenant Kernel and metadata-driven ORM router
with the original sandbox orchestrator services, tools, and REST APIs.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, List, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── New Framework Imports ─────────────────────────────────────────────────────
from thinkdome.core.api.router import router as api_router
from thinkdome.core.events.events import bus as event_bus
from thinkdome.core.kernel.kernel import Kernel
from thinkdome.core.config import get_settings
from thinkdome.core.logging import setup_logging

# ── Original API Router Imports ───────────────────────────────────────────────
from thinkdome.api.health import router as health_router
from thinkdome.api.execute import router as execute_router
from thinkdome.api.files import router as files_router
from thinkdome.api.workspaces import router as workspaces_router
from thinkdome.api.sessions import router as sessions_router
from thinkdome.api.languages import router as languages_router
from thinkdome.api.admin import router as admin_router
from thinkdome.api.observability import router as observability_router
from thinkdome.api.auth import router as auth_router
from thinkdome.api.orchestrator import router as orchestrator_router
from thinkdome.api.monitor import router as monitor_router

# ── Original Service Imports ──────────────────────────────────────────────────
from thinkdome.modules.execution.execution_service import ExecutionService
from thinkdome.modules.storage.file_service import FileService
from thinkdome.modules.storage.workspace_service import WorkspaceService
from thinkdome.modules.session.session_service import SessionService
from thinkdome.modules.database.db_service import DatabaseService
from thinkdome.modules.auth.auth_service import AuthService
from thinkdome.modules.search.search_service import SearchService
from thinkdome.modules.orchestrator.orchestrator_service import OrchestratorService
from thinkdome.modules.orchestrator.request_log_service import RequestLogService
from thinkdome.modules.billing.billing_service import BillingService

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ThinkDome API Server",
    description="Dynamic Application OS and Sandbox Orchestrator gateway",
    version="0.2.0",
)

# Enable CORS for frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Original REST APIs (/v1 prefix) ─────────────────────────────────────
app.include_router(health_router)
app.include_router(auth_router, prefix="/v1")
app.include_router(orchestrator_router, prefix="/v1")
app.include_router(execute_router, prefix="/v1")
app.include_router(files_router, prefix="/v1")
app.include_router(workspaces_router, prefix="/v1")
app.include_router(sessions_router, prefix="/v1")
app.include_router(languages_router, prefix="/v1")
app.include_router(admin_router, prefix="/v1/admin")
app.include_router(observability_router, prefix="/v1")
app.include_router(monitor_router, prefix="/v1")

# ── Mount Dynamic Metadata CRUD Router (/api prefix) ──────────────────────────
app.include_router(api_router)

# ── Mount Static Frontend Files ───────────────────────────────────────────────
static_dir = Path(__file__).resolve().parents[2] / "static"
app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")


@app.get("/")
async def serve_dashboard():
    index_path = static_dir / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/login.html")
async def serve_login():
    login_path = static_dir / "login.html"
    return HTMLResponse(content=login_path.read_text(encoding="utf-8"))


@app.get("/orchestrator_schema.json")
async def serve_schema():
    from thinkdome.modules.orchestrator.orchestrator_models import ToolUseRequest
    return JSONResponse(content=ToolUseRequest.model_json_schema())


# ── WebSocket Broadcast Registry ──────────────────────────────────────────────

active_connections: Set[WebSocket] = set()


async def broadcast_websocket_event(event_name: str, data: Any) -> None:
    """Relay internal events to active WebSocket connections."""
    payload = {"event": event_name, "data": data}
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(payload)
        except Exception:
            disconnected.append(connection)

    for conn in disconnected:
        active_connections.discard(conn)


# ── Lifecycle Hooks ───────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event() -> None:
    """Boot site kernel context and initialize original services."""
    settings = get_settings()
    setup_logging()

    # 1. Initialize multi-tenant kernel context
    kernel = Kernel.current()
    kernel.initialize()

    # 2. Register event bus broadcast hook
    event_bus.register_websocket_relay(broadcast_websocket_event)

    # 3. Initialize original DatabaseService (bound dynamically to Kernel SQLite)
    app.state.db_service = DatabaseService(settings)
    await app.state.db_service.initialize()

    # 4. Initialize TaskBroker for RabbitMQ tasks
    from thinkdome.modules.tasks.rabbitmq import TaskBroker
    app.state.task_broker = TaskBroker(settings.RABBITMQ_URL)
    try:
        await app.state.task_broker.start()
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to connect to RabbitMQ ({e}). "
            f"Stateless distributed queue scheduler will operate in local fallback execution mode."
        )
        app.state.task_broker = None

    # 5. Initialize original core service layers
    app.state.file_service = FileService(settings)
    app.state.execution_service = ExecutionService(settings)
    app.state.workspace_service = WorkspaceService(settings)
    app.state.session_service = SessionService(settings, app.state.execution_service)
    
    app.state.search_service = SearchService(settings)
    app.state.auth_service = AuthService(settings, app.state.db_service)
    app.state.request_log_service = RequestLogService(settings, app.state.db_service)
    app.state.billing_service = BillingService(app.state.db_service)

    # 6. Initialize original PoolManager and Monitoring services
    from thinkdome.modules.execution.pool_manager import PoolManager
    from thinkdome.modules.security.security_scanner import SecurityScanner
    from thinkdome.modules.monitoring.monitor_service import MonitorService
    from thinkdome.modules.auth.credential_vault import CredentialVault

    docker_client = None
    if settings.EXECUTOR_BACKEND.lower() in ("docker", "hybrid"):
        try:
            import docker
            if settings.DOCKER_TLS_VERIFY and settings.DOCKER_CERT_PATH:
                from docker.tls import TLSConfig
                tls_config = TLSConfig(
                    client_cert=(
                        os.path.join(settings.DOCKER_CERT_PATH, 'cert.pem'),
                        os.path.join(settings.DOCKER_CERT_PATH, 'key.pem')
                    ),
                    ca_cert=os.path.join(settings.DOCKER_CERT_PATH, 'ca.pem'),
                    verify=True
                )
                docker_client = docker.DockerClient(
                    base_url=settings.DOCKER_HOST,
                    tls=tls_config
                )
            else:
                docker_client = docker.DockerClient(base_url=settings.DOCKER_HOST)
        except Exception as e:
            logger.warning(f"Could not connect to Docker client: {e}")

    app.state.pool_manager = PoolManager(settings, docker_client)
    app.state.security_scanner = SecurityScanner()
    app.state.monitor_service = MonitorService(settings, docker_client)
    app.state.credential_vault = CredentialVault(settings, app.state.db_service)

    # 7. Initialize OpenAI & Anthropic Containment components
    from thinkdome.modules.execution.egress_proxy import EgressProxy
    from thinkdome.modules.tasks.scheduler import Scheduler as LegacyScheduler
    from thinkdome.harness.harness import Harness

    app.state.egress_proxy = EgressProxy()
    app.state.scheduler = LegacyScheduler(partition_count=4, max_concurrency_per_partition=50)
    app.state.harness = Harness(settings, app.state.db_service)

    # 8. Initialize Orchestrator Service with scanner and vault dependencies
    app.state.orchestrator_service = OrchestratorService(
        settings,
        app.state.execution_service,
        app.state.search_service,
        security_scanner=app.state.security_scanner,
        credential_vault=app.state.credential_vault,
    )

    logger.info("✓ ThinkDome API Gateway fully booted with integrated orchestrator services.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Gracefully close kernel database pools and original service handlers."""
    # 1. Close multi-tenant kernel connection pool
    kernel = Kernel.current()
    kernel.close()

    # 2. Close original DatabaseService asyncpg pools
    if hasattr(app.state, "db_service") and app.state.db_service:
        await app.state.db_service.close()

    # 3. Stop TaskBroker
    if hasattr(app.state, "task_broker") and app.state.task_broker:
        await app.state.task_broker.stop()

    logger.info("ThinkDome API Gateway shut down.")


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """Receive live client subscriptions and pipe kernel updates to dashboard."""
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"WebSocket client {client_id} connected.")
    try:
        while True:
            # Keep-alive loop, listening for client commands if any
            data = await websocket.receive_text()
            await websocket.send_json({"echo": data})
    except WebSocketDisconnect:
        active_connections.discard(websocket)
        logger.info(f"WebSocket client {client_id} disconnected.")
