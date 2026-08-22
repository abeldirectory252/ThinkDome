"""Authentication and session management router (JWT, HTTP-only cookies, Refresh Tokens)."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Header
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import get_auth_service
from thinkdome.security.auth.service import AuthService

router = APIRouter(tags=["auth"])

class UserCredentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    role: Optional[str] = Field(default="AGENT_STANDARD")

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str
    role: str = "AGENT_STANDARD"
    expires_in: int = 900

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/auth/register", status_code=201)
async def register(
    credentials: UserCredentials,
    request: Request,
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Register a new sandbox user."""
    success = auth_svc.register(
        credentials.username, 
        credentials.password,
        role=credentials.role or "AGENT_STANDARD",
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

    # Resolve the effective role from the ORM assignment.  The login form's
    # optional role field is not an authorization source and previously caused
    # administrators to receive AGENT_STANDARD JWTs.
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
        if username == "administrator":
            assigned_role = "SUPER_ADMIN"
        elif username == "admin":
            assigned_role = "ADMIN"

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
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        path="/"
    )

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "username": username,
        "role": assigned_role,
        "expires_in": 900
    }

@router.post("/auth/refresh")
async def refresh(
    req: RefreshRequest,
    request: Request,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Rotate single-use refresh token and issue new access token."""
    new_tokens = auth_svc.rotate_refresh_token(
        req.refresh_token,
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
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=new_tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
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
