"""FastAPI application factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from thinkdome.core.config import get_settings
from thinkdome.core.logging import setup_logging
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    setup_logging()

    # Initialize DB first and call initialize for asyncpg pool
    app.state.db_service = DatabaseService(settings)
    await app.state.db_service.initialize()

    # Initialize TaskBroker for RabbitMQ tasks
    from thinkdome.modules.tasks.rabbitmq import TaskBroker
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
    from thinkdome.modules.execution.pool_manager import PoolManager
    from thinkdome.modules.security.security_scanner import SecurityScanner
    from thinkdome.modules.monitoring.monitor_service import MonitorService
    from thinkdome.modules.auth.credential_vault import CredentialVault

    docker_client = None
    if settings.EXECUTOR_BACKEND.lower() in ("docker", "hybrid"):
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

    # Initialize OpenAI & Anthropic Containment components
    from thinkdome.modules.execution.egress_proxy import EgressProxy
    from thinkdome.modules.tasks.scheduler import Scheduler
    from thinkdome.harness.harness import Harness

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

    # â”€â”€ Global Exception Handlers â”€â”€
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        """Convert Pydantic validation errors into human-readable messages."""
        errors = exc.errors()
        messages = []
        for err in errors:
            field = " â†’ ".join(str(loc) for loc in err.get("loc", []) if loc != "body")
            msg = err.get("msg", "Invalid value")
            messages.append(f"{field}: {msg}" if field else msg)
        detail = "; ".join(messages) if messages else "Validation failed."
        return JSONResponse(
            status_code=422,
            content={"detail": detail}
        )

    @app.exception_handler(500)
    async def internal_error_handler(request, exc):
        """Catch unhandled server errors gracefully."""
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. Please try again later."}
        )

    # Setup metrics
    from thinkdome.core.metrics import setup_metrics
    setup_metrics(app, settings.EXECUTOR_BACKEND)

    # Setup tracing
    from thinkdome.core.tracing import setup_tracing
    setup_tracing(
        service_name=settings.OTEL_SERVICE_NAME,
        otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        enabled=settings.OTEL_ENABLED
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
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

    # Serve static assets
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent / "static"
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
        from thinkdome.modules.orchestrator.orchestrator_models import ToolUseRequest
        return JSONResponse(content=ToolUseRequest.model_json_schema())

    return app
