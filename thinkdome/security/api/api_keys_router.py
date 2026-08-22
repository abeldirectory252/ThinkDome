"""API Key management router with scoping and individual key revocation."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Request

from thinkdome.core.dependencies import get_auth_service, get_current_admin, get_current_user
from thinkdome.security.auth.service import AuthService

router = APIRouter(prefix="/v1/api-keys", tags=["API Keys"])


class CreateApiKeyRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100, description="Display name for the API key")
    token_type: str = Field("SDK", description="Scope / Client type: LLM, WEB, SDK, CURL, ORCH, IDE")
    rate_limit_tier: Optional[str] = Field("standard", description="Rate limit tier: free, standard, premium")
    expires_at: Optional[str] = Field(None, description="Expiration timestamp ISO format (optional)")


class ApiKeyResponse(BaseModel):
    key_id: str
    display_name: str
    token_type: str
    created_at: str
    expires_at: Optional[str] = None
    status: str
    masked_token: str
    token: Optional[str] = None  # Returned only on creation


@router.post("", response_model=ApiKeyResponse, status_code=201)
@router.post("/", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Create a new scoped API key for programmatic/curl/SDK use."""
    actor = current_user.get("username", "admin")
    client_ip = request.client.host if request.client else "unknown"
    
    key_info = auth_svc.create_api_key(
        display_name=req.display_name,
        token_type=req.token_type,
        expires_at=req.expires_at,
        creator=actor,
        actor_ip=client_ip
    )
    
    masked = f"{key_info['token'][:8]}••••••••{key_info['token'][-4:]}"
    return ApiKeyResponse(
        key_id=key_info["key_id"],
        display_name=key_info["display_name"],
        token_type=key_info["token_type"],
        created_at=key_info["created_at"],
        expires_at=key_info.get("expires_at"),
        status=key_info["status"],
        masked_token=masked,
        token=key_info["token"]
    )


@router.get("", response_model=List[ApiKeyResponse])
@router.get("/", response_model=List[ApiKeyResponse])
async def list_api_keys(
    current_user: dict = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """List all API keys (masked tokens only)."""
    keys = auth_svc.list_api_keys()
    return [
        ApiKeyResponse(
            key_id=str(k.get("key_id", "")),
            display_name=str(k.get("display_name", "")),
            token_type=str(k.get("token_type", "LLM")),
            created_at=str(k.get("created_at", "")),
            expires_at=str(k.get("expires_at")) if k.get("expires_at") is not None else None,
            status=str(k.get("status", "active")),
            masked_token=str(k.get("masked_token", "••••••••"))
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """Revoke an individual API key by ID."""
    actor = current_user.get("username", "admin")
    client_ip = request.client.host if request.client else "unknown"
    
    success = auth_svc.revoke_api_key(
        key_id=key_id,
        actor=actor,
        actor_ip=client_ip
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key '{key_id}' not found or already revoked."
        )
    return {"status": "success", "message": f"API Key '{key_id}' revoked successfully."}
