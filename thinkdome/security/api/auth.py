"""Authentication and session management router (JWT, HTTP-only cookies, Refresh Tokens)."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status, Header
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import get_auth_service, get_current_user
from thinkdome.core.config import get_settings
from thinkdome.security.auth.service import AuthService

router = APIRouter(tags=["auth"])


def _secure_cookie() -> bool:
    """Require transport-secure cookies outside local development."""
    return get_settings().DEPLOYMENT_ENV.lower() in {"staging", "production"}

class UserCredentials(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$",
    )
    password: str = Field(..., min_length=6, max_length=100)
    role: Optional[str] = Field(default="AGENT_STANDARD")

class LoginResponse(BaseModel):
    access_token: str
    session_token: Optional[str] = None
    refresh_token: str
    token_type: str = "bearer"
    username: str
    role: str = "AGENT_STANDARD"
    user: Optional[dict] = None
    expires_in: int = 900

class RefreshRequest(BaseModel):
    # Browser clients keep this token in an HTTP-only cookie.  Accepting an
    # omitted JSON value lets them refresh without exposing it to JavaScript.
    refresh_token: Optional[str] = None

@router.post("/auth/register", status_code=201)
async def register(
    credentials: UserCredentials,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Register a new sandbox user."""
    # Public self-registration can only create the least-privileged role.
    # Never trust a client-supplied role here; privileged accounts must be
    # provisioned through the admin RBAC API.
    success = auth_svc.register(
        credentials.username, 
        credentials.password,
        role="AGENT_STANDARD",
        actor_ip=request.client.host if request.client else "unknown"
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists or is invalid."
        )
    return {"status": "success", "message": "User registered successfully."}

@router.post("/auth/login", response_model=LoginResponse)
async def login(
    credentials: UserCredentials,
    request: Request,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Authenticate credentials, issue short-lived JWT access token and rotating refresh token, set HTTP-only cookies."""
    username = credentials.username.strip().lower()
    # Validate password using DB user record
    user = auth_svc.db_service.fetch_one(
        "SELECT username, hashed_password, salt FROM users WHERE username = ?", (username,)
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    hashed = auth_svc._hash_password(credentials.password, user["salt"])
    if hashed != user["hashed_password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    # Resolve the effective role exclusively from the persisted RBAC assignment.
    assigned_role = "AGENT_STANDARD"
    try:
        from thinkdome.security.repositories.user import UserRepository
        from thinkdome.security.repositories.role import RoleRepository
        from thinkdome.security.identity.core import select_effective_role
        rbac_user = UserRepository().get_by_username(username)
        assigned_role = select_effective_role(
            RoleRepository().get_user_roles(rbac_user.id) if rbac_user else [],
            username=username,
        )
    except Exception:
        # Authentication remains valid if the optional RBAC read model is
        # temporarily unavailable; authorization will use the persisted token
        # role and never infer privilege from a username.
        pass


    tokens = auth_svc.create_auth_tokens(
        username=username,
        role=assigned_role,
        actor_ip=request.client.host if request.client else "unknown"
    )

    # Set secure HTTP-only cookies
    response.set_cookie(
        key="session_token",
        value=tokens["access_token"],
        httponly=True,
        samesite="lax",
        max_age=900,
        secure=_secure_cookie(),
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        secure=_secure_cookie(),
        path="/"
    )

    user_payload = {
        "id": f"usr_{username}_01",
        "username": username,
        "role": assigned_role,
        "roles": [assigned_role]
    }

    return {
        "access_token": tokens["access_token"],
        "session_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "username": username,
        "role": assigned_role,
        "user": user_payload,
        "expires_in": 900
    }

@router.get("/auth/me")
async def get_me(
    user: dict = Depends(get_current_user),
):
    """Retrieve the authenticated user context for the React console UI."""
    username = user.get("username", "anonymous")
    role = user.get("role", "AGENT_STANDARD")

    return {
        "user": {
            "id": f"usr_{username}_01",
            "username": username,
            "role": role,
            "roles": [role]
        }
    }

@router.post("/auth/logout")
async def logout(response: Response):
    """Log out current session and delete auth cookies."""
    response.delete_cookie(key="session_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return {"status": "success"}

@router.post("/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    req: Optional[RefreshRequest] = Body(default=None),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Rotate single-use refresh token and issue new access token."""
    refresh_token = (req.refresh_token if req else None) or request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing. Please log in again."
        )
    new_tokens = auth_svc.rotate_refresh_token(
        refresh_token,
        actor_ip=request.client.host if request.client else "unknown"
    )
    if not new_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token."
        )

    response.set_cookie(
        key="session_token",
        value=new_tokens["access_token"],
        httponly=True,
        samesite="lax",
        max_age=900,
        secure=_secure_cookie(),
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=new_tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        secure=_secure_cookie(),
        path="/"
    )

    return new_tokens

@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Invalidate active JWT and refresh tokens and clear HTTP-only cookies."""
    token = None
    if authorization:
        token = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    if not token:
        token = request.cookies.get("session_token")

    if token:
        auth_svc.logout(token, actor_ip=request.client.host if request.client else "unknown")

    response.delete_cookie("session_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"status": "success", "message": "Logged out successfully."}
