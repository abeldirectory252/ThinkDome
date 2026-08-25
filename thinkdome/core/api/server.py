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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── New Framework Imports ─────────────────────────────────────────────────────
import thinkdome.platform.orchestration.tools  # Trigger tool imports and class-based tool registration
from thinkdome.core.api.router import router as api_router
from thinkdome.core.events.events import bus as event_bus
from thinkdome.core.kernel.kernel import Kernel
from thinkdome.core.config import get_settings
from thinkdome.core.logging import setup_logging
from thinkdome.core.dependencies import get_current_user

# ── Original API Router Imports ───────────────────────────────────────────────
from thinkdome.platform.observability.api.health import router as health_router
from thinkdome.api.routes.execution.execute import router as execute_router
from thinkdome.platform.storage.api.files import router as files_router
from thinkdome.platform.storage.api.workspaces import router as workspaces_router
from thinkdome.platform.storage.api.filebox import router as filebox_router
from thinkdome.sandbox.sessions.api import router as sessions_router
from thinkdome.api.routes.execution.languages import router as languages_router
from thinkdome.security.api.admin import router as admin_router
from thinkdome.api.routes.sandboxes import router as sandboxes_router
from thinkdome.platform.observability.api.observability import router as observability_router
from thinkdome.security.api.auth import router as auth_router
from thinkdome.platform.orchestration.api import router as orchestrator_router
from thinkdome.platform.observability.api.monitor import router as monitor_router
from thinkdome.api.routes.control_plane import router as control_plane_router

# ── Original Service Imports ──────────────────────────────────────────────────
from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.storage.files.service import FileService
from thinkdome.platform.storage.workspaces.service import WorkspaceService
from thinkdome.sandbox.sessions.service import SessionService
from thinkdome.platform.database.service import DatabaseService
from thinkdome.security.auth.service import AuthService
from thinkdome.platform.orchestration.search.service import SearchService
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.request_log import RequestLogService
from thinkdome.platform.billing.service import BillingService

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ThinkDome API Server",
    description="Dynamic Application OS and Sandbox Orchestrator gateway",
    version="0.2.0",
)

# Enable only explicitly configured browser origins.  Wildcard origins with
# credentials would permit unintended cross-site API calls and are rejected by
# browsers for credentialed requests anyway.
_cors_origins = get_settings().cors_allow_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
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
app.include_router(filebox_router)
app.include_router(sessions_router, prefix="/v1")
app.include_router(languages_router, prefix="/v1")
app.include_router(admin_router, prefix="/v1/admin")
app.include_router(sandboxes_router, prefix="/v1")
app.include_router(observability_router, prefix="/v1")
app.include_router(monitor_router, prefix="/v1")
app.include_router(control_plane_router, prefix="/v1")

# ── Mount Dynamic Metadata CRUD Router (/api prefix) ──────────────────────────
app.include_router(api_router)

# ── Mount Static Frontend Files ───────────────────────────────────────────────
static_dir = Path(__file__).resolve().parents[2] / "static"
compiled_console_dir = static_dir / "console"

if (compiled_console_dir / "assets").exists():
    app.mount("/console/assets", StaticFiles(directory=str(compiled_console_dir / "assets")), name="console_assets")
if (static_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")


@app.get("/")
@app.get("/index.html")
@app.get("/console")
@app.get("/console/{full_path:path}")
async def serve_dashboard(full_path: str = ""):
    index_path = static_dir / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/login.html")
async def serve_login():
    login_path = static_dir / "login.html"
    return HTMLResponse(content=login_path.read_text(encoding="utf-8"))


@app.get("/styles.css")
@app.get("/assets/css/styles.css")
async def serve_styles():
    from fastapi.responses import FileResponse
    css_path = static_dir / "assets" / "css" / "styles.css"
    if not css_path.exists():
        css_path = static_dir / "styles.css"
    return FileResponse(str(css_path), media_type="text/css")


@app.get("/orchestrator_schema.json")
async def serve_schema():
    from thinkdome.platform.orchestration.orchestrator_models import ToolUseRequest
    return JSONResponse(content=ToolUseRequest.model_json_schema())


@app.get("/favicon.ico")
async def serve_favicon():
    from fastapi import Response
    return Response(status_code=204)


@app.get("/v1/hosted/{site_id}/{filename:path}")
@app.get("/v1/hosted/{site_id}")
async def serve_hosted_site(site_id: str, filename: str = "index.html"):
    """Serve dynamically hosted HTML reports and applications with auto-expiration."""
    from fastapi.responses import FileResponse, HTMLResponse
    from pathlib import Path
    import os

    hosted_root = (Path(os.getcwd()) / "storage" / "hosted_sites").resolve()
    base_dir = (hosted_root / site_id).resolve()
    if not base_dir.exists():
        hosted_root = (Path(__file__).resolve().parents[3] / "storage" / "hosted_sites").resolve()
        base_dir = (hosted_root / site_id).resolve()

    if hosted_root not in base_dir.parents and base_dir != hosted_root:
        return HTMLResponse(content="Hosted site not found", status_code=404)

    target_file = (base_dir / (filename if filename else "index.html")).resolve()
    if base_dir not in target_file.parents and target_file != base_dir:
        # Never allow a hosted-site URL to traverse outside its site root.
        target_file = base_dir / "index.html"

    if not target_file.exists() or not target_file.is_file():
        target_file = base_dir / "index.html"

    if not target_file.exists() or not target_file.is_file():
        if base_dir.exists():
            files = [f for f in base_dir.iterdir() if f.is_file()]
            if files:
                target_file = files[0]

    if not target_file.exists() or not target_file.is_file():
        expired_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Hosted Site Expired — ThinkDome</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&family=Fira+Code:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    body {{ margin: 0; background: #ffffff; color: #0f172a; font-family: Inter, system-ui, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }}
    .login-card {{ width: 100%; max-width: 440px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 40px 36px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); text-align: center; box-sizing: border-box; }}
    .brand {{ display: flex; align-items: center; justify-content: center; gap: 10px; font-family: Outfit, sans-serif; font-size: 22px; font-weight: 800; color: #0284c7; }}
    .status-icon {{ margin: 24px auto 12px; width: 56px; height: 56px; border-radius: 50%; background: #fef2f2; border: 1px solid #fecaca; display: flex; align-items: center; justify-content: center; color: #dc2626; }}
    h1 {{ font-family: Outfit, sans-serif; font-size: 24px; font-weight: 700; margin: 16px 0 8px; color: #0f172a; }}
    .sub {{ color: #64748b; font-size: 14px; margin-bottom: 20px; line-height: 1.5; }}
    .token-badge {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 14px; border-radius: 8px; font-family: 'Fira Code', monospace; font-size: 13px; color: #0284c7; word-break: break-all; margin-bottom: 24px; }}
    .action-btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 8px; width: 100%; padding: 12px; background: #0f172a; color: #ffffff; font-weight: 600; font-size: 14px; border-radius: 8px; text-decoration: none; transition: opacity 0.2s; box-sizing: border-box; }}
    .action-btn:hover {{ opacity: 0.9; }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="brand">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m21 16-9 5-9-5V8l9-5 9 5v8Z" />
        <path d="m3.3 7 8.7 5 8.7-5" />
        <path d="M12 22V12" />
      </svg>
      <span>ThinkDome</span>
    </div>
    <div class="status-icon">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
    </div>
    <h1>Hosted Site Expired</h1>
    <p class="sub">The temporary hosted application or preview has expired (TTL timeout) or the URL is invalid.</p>
    <div class="token-badge">Token: {site_id}</div>
    <a href="/" class="action-btn">
      Return to ThinkDome Console
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
    </a>
  </div>
</body>
</html>"""
        return HTMLResponse(content=expired_html, status_code=404)

    media_type = "text/html"
    if target_file.suffix == ".css":
        media_type = "text/css"
    elif target_file.suffix == ".js":
        media_type = "application/javascript"
    elif target_file.suffix in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico"]:
        media_type = f"image/{target_file.suffix.lstrip('.')}"

    return FileResponse(target_file, media_type=media_type)


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
    from thinkdome.platform.tasks.rabbitmq import TaskBroker
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
    from thinkdome.sandbox.pool.manager import PoolManager
    from thinkdome.security.scanner.service import SecurityScanner
    from thinkdome.platform.observability.monitoring.service import MonitorService
    from thinkdome.security.auth.vault import CredentialVault

    docker_client = None
    if settings.EXECUTOR_BACKEND.lower() in ("docker", "hybrid", "microvm"):
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
    from thinkdome.sandbox.network.egress import EgressProxy
    from thinkdome.platform.tasks.scheduler import Scheduler as LegacyScheduler
    from thinkdome.sandbox.harness.harness import Harness

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
    app.state.orchestrator_service.db = app.state.db_service

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
    token = websocket.query_params.get("token") or websocket.cookies.get("session_token")
    auth_svc = getattr(websocket.app.state, "auth_service", None)
    if not token or not auth_svc or not auth_svc.verify_token(token):
        await websocket.close(code=1008, reason="Unauthorized")
        return
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


# ── MCP SSE Transport Endpoints ──────────────────────────────────────────────
from mcp.server.sse import SseServerTransport
from thinkdome.platform.orchestration.mcp_server import get_mcp_server

# Initialize SSE Transport
sse = SseServerTransport("/mcp/messages")


async def _authenticated_mcp_messages(scope, receive, send):
    """Protect the POST half of MCP SSE; mounts bypass FastAPI dependencies."""
    max_message_bytes = get_settings().MCP_MAX_MESSAGE_BYTES
    if scope.get("type") == "http":
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        try:
            if int(headers.get("content-length", "0")) > max_message_bytes:
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"MCP message too large"}'})
                return
        except ValueError:
            await send({"type": "http.response.start", "status": 400,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Invalid Content-Length"}'})
            return
        auth = headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else auth
        if not token:
            cookie = headers.get("cookie", "")
            token = next((part.split("=", 1)[1] for part in cookie.split("; ")
                          if part.startswith("session_token=") and "=" in part), "")
        auth_svc = getattr(app.state, "auth_service", None)
        if not token or not auth_svc or not auth_svc.verify_token(token):
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Unauthorized"}'})
            return
    received_bytes = 0

    async def bounded_receive():
        nonlocal received_bytes
        message = await receive()
        if message.get("type") == "http.request":
            received_bytes += len(message.get("body", b""))
            if received_bytes > max_message_bytes:
                return {"type": "http.disconnect"}
        return message

    await sse.handle_post_message(scope, bounded_receive, send)

@app.get("/mcp/sse")
async def handle_sse(request: Request, user: dict = Depends(get_current_user)):
    """Establish SSE stream connection for MCP."""
    kernel = Kernel.current()
    db_service = request.app.state.db_service
    orchestrator = request.app.state.orchestrator_service
    from thinkdome.security.identity.core import UserIdentity

    client_ip = request.client.host if request.client else "127.0.0.1"
    mcp_server = get_mcp_server(
        kernel.site_name,
        db_service,
        orchestrator,
        client_ip=client_ip,
        identity=UserIdentity.from_dict(user),
    )

    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )

# Mount POST message endpoint
app.mount("/mcp/messages", _authenticated_mcp_messages)
