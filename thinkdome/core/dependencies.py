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
from thinkdome.control_plane.lifecycle import ControlPlaneLifecycle


def user_has_workspace_permission(user: dict, module: str, resource: str, action: str) -> bool:
    """Evaluate an explicit permission using the persisted workspace policy context."""
    from thinkdome.security.identity.core import RolePolicyEngine, UserIdentity
    return RolePolicyEngine.has_permission(UserIdentity.from_dict(user), f"{module}:{resource}:{action}")


def user_is_workspace_admin(user: dict) -> bool:
    """Check a persisted administrative grant; role labels alone grant no authority."""
    return user_has_workspace_permission(user, "system", "admin", "manage")


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


def get_control_plane_lifecycle(request: Request) -> ControlPlaneLifecycle:
    """Return the ORM-backed placement/lifecycle coordinator."""
    return request.app.state.control_plane_lifecycle


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
    path = request.url.path.rstrip("/")
    # Login and account creation are the only public authentication operations.
    if path.startswith("/v1/auth/") and path.rsplit("/", 1)[-1] in {"login", "register", "refresh", "me", "logout"}:
        return user_info

    route = request.scope.get("route")
    route_name = getattr(route, "name", None)
    if path.startswith(("/v1/", "/api/")) and route_name:
        method_actions = {"GET": "read", "HEAD": "read", "POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
        action = method_actions.get(request.method.upper())
        if action:
            from thinkdome.security.identity.core import RolePolicyEngine, UserIdentity
            identity = UserIdentity.from_dict(user_info)
            required = f"api:{route_name}:{action}"
            if not RolePolicyEngine.has_permission(identity, required):
                from fastapi import HTTPException, status
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: '{required}' is required.")
    return user_info


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    from thinkdome.security.identity.core import RolePolicyEngine, UserIdentity
    identity = UserIdentity.from_dict(current_user)
    if not RolePolicyEngine.has_permission(identity, "system:admin:manage"):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin or Orchestrator access required."
        )
    return current_user


async def get_current_audit_viewer(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Allow admins and auditors to inspect only permitted audit data."""
    if user_is_workspace_admin(current_user) or user_has_workspace_permission(current_user, "system", "audit", "read"):
        return current_user
    from fastapi import HTTPException, status
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: audit viewer, standard agent, or administrator access required.",
    )
