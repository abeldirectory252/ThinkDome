"""Authentication REST API Router (JWT, Login, Refresh, Sessions)."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse

from thinkdome.security.rbac.service import UserService, hash_password
from thinkdome.security.repositories.user import UserRepository
from thinkdome.security.repositories.audit import AuditRepository
from thinkdome.core.dependencies import get_auth_service, get_current_user

router = APIRouter(prefix="/v1/auth", tags=["RBAC Auth"])

user_repo = UserRepository()
audit_repo = AuditRepository()


class LoginRequest(BaseModel):
    username: str = Field(description="Username or email")
    password: str = Field(description="Account password")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(description="Refresh Token")


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    """Authenticate user credentials and issue session token."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    user = user_repo.get_by_username(req.username) or user_repo.get_by_email(req.username)

    if not user or user.password_hash != hash_password(req.password):
        if user:
            audit_repo.record_login(user.id, status="failed", ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is currently '{user.status}'."
        )

    # Update last login timestamp
    user._values["last_login"] = time.strftime("%Y-%m-%d %H:%M:%S")
    user.save()

    session_token = f"session_{uuid.uuid4().hex}"
    expires_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 86400))
    audit_repo.create_session(user.id, session_token, expires_at, ip_address=client_ip)
    audit_repo.record_login(user.id, status="success", ip_address=client_ip)

    return {
        "status": "success",
        "session_token": session_token,
        "token_type": "Bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "status": user.status
        }
    }


@router.post("/logout")
async def logout(request: Request, current_user: dict = Depends(get_current_user)):
    """Revoke user active session token."""
    token = request.headers.get("Authorization") or request.headers.get("X-Session-Token")
    if token and token.startswith("Bearer "):
        token = token[7:]
    if token:
        audit_repo.revoke_session(token)
    return {"status": "success", "message": "Logged out successfully."}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Fetch current user identity context."""
    user = user_repo.get_by_id(current_user.get("id", ""))
    profile = user_repo.get_profile(user.id) if user else None

    return {
        "user": user.to_dict() if user else current_user,
        "profile": profile.to_dict() if profile else {}
    }
