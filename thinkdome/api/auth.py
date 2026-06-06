"""Authentication and session management router."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, Header
from pydantic import BaseModel, Field

from thinkdome.api.dependencies import get_auth_service
from thinkdome.services.auth_service import AuthService

router = APIRouter(tags=["auth"])

class UserCredentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str

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
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Authenticate and get a session token."""
    token = auth_svc.login(
        credentials.username, 
        credentials.password,
        actor_ip=request.client.host if request.client else "unknown"
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": credentials.username.lower()
    }

@router.post("/auth/logout")
async def logout(
    request: Request,
    authorization: Optional[str] = Header(None),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Invalidate active session token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header."
        )
    
    token = authorization
    if authorization.lower().startswith("bearer "):
        token = authorization[7:]
        
    success = auth_svc.logout(
        token,
        actor_ip=request.client.host if request.client else "unknown"
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session token."
        )
    return {"status": "success", "message": "Logged out successfully."}

