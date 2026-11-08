"""Authentication and session management router (JWT, HTTP-only cookies, Refresh Tokens)."""

from __future__ import annotations

import hmac
import re
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status, Header
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import get_auth_service, get_current_user
from thinkdome.core.config import get_settings
from thinkdome.security.auth.service import AuthService
from thinkdome.security.repositories.role import RoleRepository
from thinkdome.security.rbac.service import UserService

router = APIRouter(tags=["auth"])
user_service = UserService()


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
    password: str = Field(..., min_length=8, max_length=100)

class RegistrationRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$")
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=12, max_length=100)
    first_name: str = Field(..., min_length=1, max_length=80)
    last_name: str = Field(..., min_length=1, max_length=80)
    phone: Optional[str] = Field(default="", max_length=30)
    department: Optional[str] = Field(default="", max_length=100)
    department_id: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default="", max_length=100)
    organization: Optional[str] = Field(default="", max_length=100)
    avatar_url: Optional[str] = Field(default="", max_length=500)
    bio: Optional[str] = Field(default="", max_length=1000)
    timezone: Optional[str] = Field(default="UTC", max_length=50)
    locale: Optional[str] = Field(default="en-US", max_length=20)

class LoginResponse(BaseModel):
    access_token: str
    session_token: Optional[str] = None
    refresh_token: str
    token_type: str = "bearer"
    username: str
    role: Optional[str] = None
    user: Optional[dict] = None
    expires_in: int = 900

class RefreshRequest(BaseModel):
    # Browser clients keep this token in an HTTP-only cookie.  Accepting an
    # omitted JSON value lets them refresh without exposing it to JavaScript.
    refresh_token: Optional[str] = None

@router.post("/auth/register", status_code=201)
async def register(
    credentials: RegistrationRequest,
):
    """Register a new sandbox user with full profile fields and dynamic role allocation."""
    # Public self-registration can only create the least-privileged role.
    # Never trust a client-supplied role here; privileged accounts must be
    # provisioned through the admin RBAC API.
    email = credentials.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a valid email address."
        )
    if not credentials.first_name.strip() or not credentials.last_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="First and last name are required."
        )
    try:
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        from thinkdome.security.rbac.models import Role
        new_user = user_service.create_user(
            username=credentials.username,
            email=email,
            password=credentials.password,
            first_name=credentials.first_name.strip(),
            last_name=credentials.last_name.strip(),
            phone=credentials.phone or "",
            department_id=credentials.department_id or (credentials.department if credentials.department else None),
            designation=credentials.designation or "",
            avatar_url=credentials.avatar_url or "",
            organization=credentials.organization or "",
            bio=credentials.bio or "",
            timezone=credentials.timezone or "UTC",
            locale=credentials.locale or "en-US",
            actor="self-registration",
        )
        standard_role_name = dynamic_role_protocol.get_default_role()
        standard_role = RoleRepository().get_by_name(standard_role_name)
        if not standard_role:
            standard_role = Role(name=standard_role_name, description=f"{standard_role_name} member role", is_active=True)
            standard_role.save()
        user_service.assign_role_to_user(new_user.id, standard_role.id, actor="self-registration")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "success", "message": "Account created. You can now log in with your sandbox credentials."}

@router.post("/auth/login", response_model=LoginResponse)
async def login(
    credentials: UserCredentials,
    request: Request,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Authenticate credentials, issue short-lived JWT access token and rotating refresh token, set HTTP-only cookies."""
    username = credentials.username.strip().lower()
    # RBAC is the canonical authentication store. Existing installations may
    # still have accounts in the legacy ``users`` table; the compatibility
    # path below upgrades those accounts after a successful verification.
    authenticated = user_service.authenticate(username, credentials.password)
    if not authenticated:
        # Existing installations may still contain accounts in the original
        # salted ``users`` table.  Verify those credentials against the
        # legacy hash, then upgrade the account into RBAC using the plaintext
        # password supplied for this request.  This is a one-time compatibility
        # path; subsequent logins use the canonical RBAC record.
        legacy_user = auth_svc.db_service.fetch_one(
            "SELECT username, hashed_password, salt FROM users WHERE username = ?",
            (username,),
        )
        if legacy_user and hmac.compare_digest(
            auth_svc._hash_password(credentials.password, legacy_user["salt"]),
            legacy_user["hashed_password"],
        ):
            try:
                migrated_user = user_service.create_user(
                    username=username,
                    email=f"{username}@enterprise.local",
                    password=credentials.password,
                    actor="legacy-auth-migration",
                )
                from thinkdome.security.rbac.protocol import dynamic_role_protocol
                role_repo = RoleRepository()
                standard_role_name = dynamic_role_protocol.get_default_role()
                standard_role = role_repo.get_by_name(standard_role_name)
                if standard_role:
                    user_service.assign_role_to_user(
                        migrated_user.id,
                        standard_role.id,
                        actor="legacy-auth-migration",
                    )
                authenticated = user_service.authenticate(username, credentials.password)
            except ValueError:
                # Another request may have migrated the account concurrently.
                authenticated = user_service.authenticate(username, credentials.password)
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    rbac_user, assigned_role = authenticated


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
        "id": rbac_user.id,
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
