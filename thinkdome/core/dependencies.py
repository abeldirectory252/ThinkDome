"""FastAPI dependency injection helpers."""

from fastapi import Request, Depends

from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.storage.files.service import FileService
from thinkdome.platform.storage.workspaces.service import WorkspaceService
from thinkdome.sandbox.sessions.service import SessionService
from thinkdome.security.auth.service import AuthService
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.request_log import RequestLogService
from thinkdome.platform.billing.service import BillingService


def get_execution_service(request: Request) -> ExecutionService:
    return request.app.state.execution_service


def get_file_service(request: Request) -> FileService:
    return request.app.state.file_service


def get_workspace_service(request: Request) -> WorkspaceService:
    return request.app.state.workspace_service


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_orchestrator_service(request: Request) -> OrchestratorService:
    return request.app.state.orchestrator_service


def get_request_log_service(request: Request) -> RequestLogService:
    return request.app.state.request_log_service


def get_billing_service(request: Request) -> BillingService:
    return request.app.state.billing_service


def get_snapshot_service(request: Request):
    if not hasattr(request.app.state, "snapshot_service"):
        from thinkdome.sandbox.snapshots.service import SnapshotService
        request.app.state.snapshot_service = SnapshotService(request.app.state.execution_service.settings)
    return request.app.state.snapshot_service



async def get_current_user(
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service),
) -> dict:
    # Try header first
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
        else:
            token = auth_header

    # Fallback to custom header
    if not token:
        token = request.headers.get("X-Session-Token")

    # Fallback to query parameter (useful for SSE or file downloads)
    if not token:
        token = request.query_params.get("token")

    # Fallback to cookies
    if not token:
        token = request.cookies.get("session_token")

    if not token:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token is missing. Please log in first."
        )

    user_info = auth_svc.verify_token(token)
    if not user_info:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please log in again."
        )
    return user_info


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    if current_user.get("role") not in ("ADMIN", "ORCH"):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin or Orchestrator access required."
        )
    return current_user
