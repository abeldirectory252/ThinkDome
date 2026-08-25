"""FastAPI application factory."""

from contextlib import asynccontextmanager
import asyncio
import logging
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

import thinkdome.platform.orchestration.tools  # Trigger tool imports and class-based tool registration
from thinkdome.core.config import get_settings
from thinkdome.core.logging import setup_logging
from thinkdome.platform.observability.api.health import router as health_router
from thinkdome.core.dependencies import get_current_user
from thinkdome.api.routes.execution.execute import router as execute_router
from thinkdome.platform.storage.api.files import router as files_router
from thinkdome.platform.storage.api.workspaces import router as workspaces_router
from thinkdome.sandbox.sessions.api import router as sessions_router
from thinkdome.api.routes.execution.languages import router as languages_router
from thinkdome.security.api.admin import router as admin_router
from thinkdome.platform.observability.api.observability import router as observability_router
from thinkdome.security.api.auth import router as auth_router
from thinkdome.platform.orchestration.api import router as orchestrator_router
from thinkdome.platform.observability.api.monitor import router as monitor_router
from thinkdome.api.routes.control_plane import router as control_plane_router

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    settings.validate_production_runtime()
    setup_logging()

    # Initialize DB first and call initialize for asyncpg pool
    app.state.db_service = DatabaseService(settings)
    await app.state.db_service.initialize()

    # RBAC models use the framework ORM, whose active database is available
    # only after the application database service has been initialized.
    from thinkdome.security.rbac.schema import initialize_rbac_schema
    initialize_rbac_schema(app.state.db_service)

    # Control-plane state is persisted through the custom ORM.  This service is
    # deliberately independent from the local execution backend so public API
    # workers can schedule onto remote node agents.
    from thinkdome.control_plane.lifecycle import ControlPlaneLifecycle
    from thinkdome.control_plane.repository import ControlPlaneRepository
    app.state.control_plane_repository = ControlPlaneRepository()
    app.state.control_plane_lifecycle = ControlPlaneLifecycle(
        app.state.control_plane_repository
    )

    # Initialize TaskBroker for RabbitMQ tasks
    from thinkdome.platform.tasks.rabbitmq import TaskBroker
    app.state.task_broker = None
    if settings.RABBITMQ_URL.strip():
        app.state.task_broker = TaskBroker(settings.RABBITMQ_URL)
        try:
            # Dependency startup must be bounded.  A missing broker must
            # degrade to the local scheduler instead of hanging every worker.
            await asyncio.wait_for(app.state.task_broker.start(), timeout=5.0)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"⚠️ Failed to connect to RabbitMQ ({e}). "
                f"Stateless distributed queue scheduler will operate in local fallback execution mode."
            )
            app.state.task_broker = None

    # Initialize services
    app.state.file_service = FileService(settings)
    app.state.execution_service = ExecutionService(settings)
    app.state.workspace_service = WorkspaceService(settings)
    app.state.session_service = SessionService(settings, app.state.execution_service)
    
    # Initialize Search, Auth, Request Log, Billing Services
    app.state.search_service = SearchService(settings)
    app.state.auth_service = AuthService(settings, app.state.db_service)
    app.state.request_log_service = RequestLogService(settings, app.state.db_service)
    app.state.billing_service = BillingService(app.state.db_service)

    # Initialize PoolManager, MonitorService, SecurityScanner, CredentialVault
    from thinkdome.sandbox.pool.manager import PoolManager
    from thinkdome.security.scanner.service import SecurityScanner
    from thinkdome.platform.observability.monitoring.service import MonitorService
    from thinkdome.security.auth.vault import CredentialVault
    from thinkdome.sandbox.core.lifecycle_service import SandboxLifecycleService
    from thinkdome.sandbox.core.diagnostics_service import DiagnosticsService

    docker_client = None
    if settings.EXECUTOR_BACKEND.lower() in ("docker", "hybrid", "microvm"):
        try:
            import docker
            # support DOCKER_HOST with mutual TLS
            if settings.DOCKER_TLS_VERIFY and settings.DOCKER_CERT_PATH:
                from docker.tls import TLSConfig
                import os
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
            import logging
            logging.getLogger(__name__).warning(f"Could not connect to Docker client: {e}")

    app.state.pool_manager = PoolManager(settings, docker_client)
    app.state.security_scanner = SecurityScanner()
    app.state.monitor_service = MonitorService(settings, docker_client)
    app.state.credential_vault = CredentialVault(settings, app.state.db_service)
    app.state.lifecycle_service = SandboxLifecycleService(docker_client=docker_client)
    app.state.diagnostics_service = DiagnosticsService(docker_client=docker_client)

    # Validate secure container runtime at startup
    from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup
    validate_secure_runtime_on_startup(settings, docker_client=docker_client)

    # Initialize OpenAI & Anthropic Containment components
    from thinkdome.sandbox.network.egress import EgressProxy
    from thinkdome.platform.tasks.scheduler import Scheduler
    from thinkdome.sandbox.harness.harness import Harness

    app.state.egress_proxy = EgressProxy()
    app.state.scheduler = Scheduler(partition_count=4, max_concurrency_per_partition=50)
    app.state.harness = Harness(settings, app.state.db_service)

    # Initialize Orchestrator Service with scanner and vault dependencies
    app.state.orchestrator_service = OrchestratorService(
        settings,
        app.state.execution_service,
        app.state.search_service,
        security_scanner=app.state.security_scanner,
        credential_vault=app.state.credential_vault,
    )
    app.state.orchestrator_service.db = app.state.db_service

    await app.state.execution_service.initialize()
    python_executor = app.state.execution_service._executors.get("python")
    if python_executor and hasattr(python_executor, "set_pool_manager"):
        python_executor.set_pool_manager(app.state.pool_manager)

    if settings.POOL_ENABLED:
        await app.state.pool_manager.start()
    await app.state.monitor_service.start()
    
    # Initialize background Sandbox Reaper
    from thinkdome.sandbox.core.reaper import SandboxReaper
    from thinkdome.platform.storage.filebox.service import FileBoxService
    app.state.reaper = SandboxReaper(app.state.lifecycle_service, app.state.db_service)
    await app.state.reaper.start()
    app.state.filebox_service = FileBoxService(settings)
    # Initialize semantic FileBox folders for every known ORM user before the
    # API accepts requests. Missing folders are recreated safely on restart.
    try:
        from thinkdome.security.rbac.models import User
        for user in User.query().all():
            app.state.filebox_service.ensure_layout(
                tenant_id="default",
                owner_id=user.username,
            )
    except Exception as exc:
        logging.getLogger(__name__).warning("FileBox layout initialization failed: %s", exc)
    async def _filebox_reaper():
        while True:
            try:
                app.state.filebox_service.reap_expired()
            except Exception as exc:
                logging.getLogger(__name__).warning("FileBox reaper error: %s", exc)
            await asyncio.sleep(30)
    app.state.filebox_reaper_task = asyncio.create_task(_filebox_reaper())

    yield

    # Cleanup
    await app.state.reaper.stop()
    app.state.filebox_reaper_task.cancel()
    await app.state.scheduler.stop()
    if getattr(app.state, "task_broker", None):
        await app.state.task_broker.stop()
    await app.state.monitor_service.stop()
    await app.state.pool_manager.stop()
    await app.state.session_service.cleanup_all()
    await app.state.execution_service.shutdown()
    await app.state.db_service.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="thinkBox",
        description="Secure dynamic code sandbox for AI agents",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── Global Exception Handlers ──
    from fastapi.exceptions import RequestValidationError, HTTPException
    from fastapi.responses import JSONResponse
    from thinkdome.core.error_codes import normalize_error_detail, SandboxErrorCodes

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        """Flatten FastAPI HTTPException payload to standard error schema {"code": ..., "message": ...}."""
        content = normalize_error_detail(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        """Convert Pydantic validation errors into standard error schema."""
        errors = exc.errors()
        messages = []
        for err in errors:
            field = " -> ".join(str(loc) for loc in err.get("loc", []) if loc != "body")
            msg = err.get("msg", "Invalid value")
            messages.append(f"{field}: {msg}" if field else msg)
        detail = "; ".join(messages) if messages else "Validation failed."
        return JSONResponse(
            status_code=422,
            content={"code": SandboxErrorCodes.VALIDATION_FAILED, "message": detail}
        )

    @app.exception_handler(500)
    async def internal_error_handler(request, exc):
        """Catch unhandled server errors gracefully."""
        return JSONResponse(
            status_code=500,
            content={"code": SandboxErrorCodes.UNKNOWN_ERROR, "message": "An internal server error occurred. Please try again later."}
        )

    # Setup metrics
    from thinkdome.platform.observability.metrics.prometheus import setup_metrics
    setup_metrics(app, settings.EXECUTOR_BACKEND)

    # Setup tracing
    from thinkdome.platform.observability.tracing.telemetry import setup_tracing
    setup_tracing(
        service_name=settings.OTEL_SERVICE_NAME,
        otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        enabled=settings.OTEL_ENABLED
    )

    from thinkdome.core.middleware.request_id import RequestIdMiddleware
    from thinkdome.core.middleware.date_header import DateHeaderMiddleware

    app.add_middleware(RequestIdMiddleware)
    cors_origins = settings.cors_allow_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from thinkdome.security.api.auth_rbac import router as rbac_auth_router
    from thinkdome.security.api.users import router as rbac_users_router
    from thinkdome.security.api.roles import router as rbac_roles_router
    from thinkdome.security.api.permissions import router as rbac_permissions_router
    from thinkdome.security.api.audit import router as rbac_audit_router
    from thinkdome.sandbox.snapshots.api import router as snapshots_router
    from thinkdome.sandbox.executors.microvm.api import router as microvm_router
    from thinkdome.api.routes.execution.lifecycle import router as lifecycle_router
    from thinkdome.api.routes.execution.diagnostics import router as diagnostics_router
    from thinkdome.api.routes.execution.metadata import router as metadata_router
    from thinkdome.platform.observability.api.sdk_metrics import router as sdk_metrics_router
    from thinkdome.security.api.vault import router as vault_router
    from thinkdome.api.routes.execution.network_audit import router as network_audit_router
    from thinkdome.security.api.api_keys_router import router as api_keys_router
    from thinkdome.platform.storage.api.filebox import router as filebox_router

    # Register routers
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/v1")
    app.include_router(api_keys_router)
    app.include_router(filebox_router)
    app.include_router(rbac_auth_router)
    app.include_router(rbac_users_router)
    app.include_router(rbac_roles_router)
    app.include_router(rbac_permissions_router)
    app.include_router(rbac_audit_router)
    app.include_router(orchestrator_router, prefix="/v1")
    app.include_router(execute_router, prefix="/v1")
    app.include_router(files_router, prefix="/v1")
    app.include_router(workspaces_router, prefix="/v1")
    app.include_router(sessions_router, prefix="/v1")
    app.include_router(languages_router, prefix="/v1")
    app.include_router(admin_router, prefix="/v1/admin")
    app.include_router(observability_router, prefix="/v1")
    app.include_router(monitor_router, prefix="/v1")
    app.include_router(snapshots_router, prefix="/v1")
    app.include_router(microvm_router, prefix="/v1")
    app.include_router(lifecycle_router, prefix="/v1")
    app.include_router(diagnostics_router, prefix="/v1")
    app.include_router(metadata_router, prefix="/v1")
    app.include_router(sdk_metrics_router, prefix="/v1")
    app.include_router(vault_router, prefix="/v1")
    app.include_router(network_audit_router, prefix="/v1")
    app.include_router(control_plane_router, prefix="/v1")

    # Serve static assets
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent.parent / "static"
    compiled_console_dir = static_dir / "console"

    if (compiled_console_dir / "assets").exists():
        app.mount("/console/assets", StaticFiles(directory=str(compiled_console_dir / "assets")), name="console_assets")
    if (static_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # Serve dashboard and schema
    @app.get("/")
    @app.get("/console")
    @app.get("/console/{full_path:path}")
    async def serve_dashboard(full_path: str = ""):
        from fastapi.responses import HTMLResponse
        if full_path or (compiled_console_dir / "index.html").exists():
            console_index = compiled_console_dir / "index.html"
            if console_index.exists():
                return HTMLResponse(content=console_index.read_text(encoding="utf-8"))
        index_path = static_dir / "index.html"
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    @app.get("/login.html")
    async def serve_login():
        from fastapi.responses import HTMLResponse
        login_path = static_dir / "login.html"
        return HTMLResponse(content=login_path.read_text(encoding="utf-8"))

    @app.get("/orchestrator_schema.json")
    async def serve_schema():
        from fastapi.responses import JSONResponse
        from thinkdome.platform.orchestration.orchestrator_models import ToolUseRequest
        return JSONResponse(content=ToolUseRequest.model_json_schema())

    @app.get("/v1/hosted/{site_id}/{filename:path}")
    @app.get("/v1/hosted/{site_id}")
    async def serve_hosted_site(site_id: str, filename: str = "index.html"):
        """Serve dynamically hosted HTML reports with login.html-styled expiration notice."""
        from fastapi.responses import FileResponse, HTMLResponse
        from pathlib import Path
        import os

        from thinkdome.core.config import get_settings, get_workspace_root
        storage_dir = Path(get_settings().FILE_STORAGE_DIR)
        if not storage_dir.is_absolute():
            storage_dir = get_workspace_root() / storage_dir
        hosted_root = (storage_dir / "hosted_sites").resolve()
        base_dir = (hosted_root / site_id).resolve()
        if hosted_root not in base_dir.parents:
            return HTMLResponse(content="Hosted site not found", status_code=404)

        base_dir = base_dir.resolve()
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
            import html
            safe_site_id = html.escape(site_id)
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
    <div class="token-badge">Token: {safe_site_id}</div>
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

    # ── MCP SSE Transport Endpoints ──────────────────────────────────────────────
    from fastapi import Request
    from mcp.server.sse import SseServerTransport
    from thinkdome.platform.orchestration.mcp_server import get_mcp_server

    sse = SseServerTransport("/mcp/messages")

    async def _authenticated_mcp_messages(scope, receive, send):
        """Protect mounted MCP POST messages with the same auth as SSE."""
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
        """Establish SSE stream connection for MCP with authentication propagation."""
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.current()
        db_service = request.app.state.db_service
        orchestrator = request.app.state.orchestrator_service

        from thinkdome.security.identity.core import UserIdentity

        client_ip = request.client.host if request.client else "127.0.0.1"
        identity = UserIdentity.from_dict({
            "username": user.get("workspace_id", user.get("username", "anonymous")),
            "role": user.get("role", "AGENT_STANDARD"),
            "tenant_id": user.get("tenant_id", kernel.site_name),
        })

        mcp_server = get_mcp_server(
            kernel.site_name,
            db_service,
            orchestrator,
            client_ip=client_ip,
            identity=identity,
        )

        async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    app.mount("/mcp/messages", _authenticated_mcp_messages)

    return app
