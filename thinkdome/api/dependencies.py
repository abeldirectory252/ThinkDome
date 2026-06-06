"""FastAPI dependency injection helpers."""

from fastapi import Request, Depends

from thinkdome.services.execution_service import ExecutionService
from thinkdome.services.file_service import FileService
from thinkdome.services.workspace_service import WorkspaceService
from thinkdome.services.session_service import SessionService
from thinkdome.services.auth_service import AuthService
from thinkdome.services.orchestrator_service import OrchestratorService
from thinkdome.services.request_log_service import RequestLogService


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
    if current_user.get("role") != "ADMIN":
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access required."
        )
    return current_user
