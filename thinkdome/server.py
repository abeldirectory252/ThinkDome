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

from thinkdome.services.execution_service import ExecutionService
from thinkdome.services.file_service import FileService
from thinkdome.services.workspace_service import WorkspaceService
from thinkdome.services.session_service import SessionService
from thinkdome.services.db_service import DatabaseService
from thinkdome.services.auth_service import AuthService
from thinkdome.services.search_service import SearchService
from thinkdome.services.orchestrator_service import OrchestratorService
from thinkdome.services.request_log_service import RequestLogService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    setup_logging()

    # Initialize DB first
    app.state.db_service = DatabaseService(settings)

    # Initialize services
    app.state.file_service = FileService(settings)
    app.state.execution_service = ExecutionService(settings)
    app.state.workspace_service = WorkspaceService(settings)
    app.state.session_service = SessionService(settings, app.state.execution_service)
    
    # Initialize Search, Auth and Orchestrator Services
    app.state.search_service = SearchService(settings)
    app.state.auth_service = AuthService(settings, app.state.db_service)
    app.state.request_log_service = RequestLogService(settings, app.state.db_service)
    app.state.orchestrator_service = OrchestratorService(
        settings,
        app.state.execution_service,
        app.state.search_service,
    )

    await app.state.execution_service.initialize()

    yield

    # Cleanup
    await app.state.session_service.cleanup_all()
    await app.state.execution_service.shutdown()


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

    # Serve dashboard and schema
    @app.get("/")
    async def serve_dashboard():
        from fastapi.responses import HTMLResponse
        from pathlib import Path
        index_path = Path(__file__).resolve().parent / "static" / "index.html"
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    @app.get("/orchestrator_schema.json")
    async def serve_schema():
        from fastapi.responses import JSONResponse
        from thinkdome.models.orchestrator import ToolUseRequest
        return JSONResponse(content=ToolUseRequest.model_json_schema())

    return app
