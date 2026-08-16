"""FastAPI application factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import thinkdome.platform.orchestration.tools  # Trigger tool imports and class-based tool registration
from thinkdome.core.config import get_settings
from thinkdome.core.logging import setup_logging
from thinkdome.platform.observability.api.health import router as health_router
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
    setup_logging()

    # Initialize DB first and call initialize for asyncpg pool
    app.state.db_service = DatabaseService(settings)
    await app.state.db_service.initialize()

    # Initialize TaskBroker for RabbitMQ tasks
    from thinkdome.platform.tasks.rabbitmq import TaskBroker
    app.state.task_broker = TaskBroker(settings.RABBITMQ_URL)
    try:
        await app.state.task_broker.start()
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

    await app.state.execution_service.initialize()
    python_executor = app.state.execution_service._executors.get("python")
    if python_executor and hasattr(python_executor, "set_pool_manager"):
        python_executor.set_pool_manager(app.state.pool_manager)

    if settings.POOL_ENABLED:
        await app.state.pool_manager.start()
    await app.state.monitor_service.start()
    
    # Start scheduler facade with task broker
    await app.state.scheduler.start(
        executor_fn=app.state.orchestrator_service.execute_tool,
        broker=app.state.task_broker
    )

    yield

    # Cleanup
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from thinkdome.security.api.auth_rbac import router as rbac_auth_router
    from thinkdome.security.api.users import router as rbac_users_router
    from thinkdome.security.api.roles import router as rbac_roles_router
    from thinkdome.security.api.permissions import router as rbac_permissions_router
    from thinkdome.security.api.audit import router as rbac_audit_router
    from thinkdome.security.rbac.schema import initialize_rbac_schema

    try:
        initialize_rbac_schema(app.state.db_service)
    except Exception as ie:
        import logging
        logging.getLogger(__name__).warning(f"RBAC Schema init note: {ie}")

    from thinkdome.sandbox.snapshots.api import router as snapshots_router
    from thinkdome.sandbox.executors.microvm.api import router as microvm_router
    from thinkdome.api.routes.execution.lifecycle import router as lifecycle_router
    from thinkdome.api.routes.execution.diagnostics import router as diagnostics_router
    from thinkdome.api.routes.execution.metadata import router as metadata_router
    from thinkdome.platform.observability.api.sdk_metrics import router as sdk_metrics_router
    from thinkdome.security.api.vault import router as vault_router
    from thinkdome.api.routes.execution.network_audit import router as network_audit_router

    # Register routers
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/v1")
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

    # Serve static assets
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent.parent / "static"

    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # Serve dashboard and schema
    @app.get("/")
    async def serve_dashboard():
        from fastapi.responses import HTMLResponse
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

    # ── MCP SSE Transport Endpoints ──────────────────────────────────────────────
    from fastapi import Request
    from mcp.server.sse import SseServerTransport
    from thinkdome.platform.orchestration.mcp_server import get_mcp_server

    sse = SseServerTransport("/mcp/messages")

    @app.get("/mcp/sse")
    async def handle_sse(request: Request):
        """Establish SSE stream connection for MCP with authentication propagation."""
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.current()
        db_service = request.app.state.db_service
        orchestrator = request.app.state.orchestrator_service

        from thinkdome.security.identity.core import ROLE_ADMIN, UserIdentity

        client_ip = request.client.host if request.client else "127.0.0.1"
        caller_role = request.headers.get("X-User-Role", ROLE_ADMIN)
        username = request.headers.get("X-Username", "anonymous")
        tenant_id = request.headers.get("X-Tenant-Id", kernel.site_name)

        identity = UserIdentity.from_dict({
            "username": username,
            "role": caller_role,
            "tenant_id": tenant_id,
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

    app.mount("/mcp/messages", sse.handle_post_message)

    return app
