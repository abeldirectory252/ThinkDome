"""FastAPI endpoints for Credential Vault binding and credential management.

Implements OpenSandbox-compatible Credential Vault APIs for outbound secret brokerage.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from thinkdome.core.error_codes import SandboxErrorCodes
from thinkdome.security.auth.vault_bindings import Credential, CredentialBinding
from thinkdome.core.dependencies import get_current_user

router = APIRouter(tags=["Credential Vault"], dependencies=[Depends(get_current_user)])


class CreateVaultRequest(BaseModel):
    """Payload for setting up credentials and bindings in Vault."""
    credentials: List[Credential]
    bindings: List[CredentialBinding]


@router.post(
    "/sandboxes/{sandbox_id}/vault",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Credentials and bindings registered in Vault"},
        400: {"description": "Malformed request or invalid binding"},
        404: {"description": "Sandbox not found"},
    },
)
def create_vault_entries(
    request: Request,
    sandbox_id: str,
    payload: CreateVaultRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user: dict = Depends(get_current_user),
) -> dict:
    """Store credentials and bindings in Vault for a sandbox.

    Plaintext credential values are write-only and encrypted at rest.
    """
    vault = getattr(request.app.state, "credential_vault", None)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": SandboxErrorCodes.UNKNOWN_ERROR, "message": "Credential Vault is not initialized."},
        )

    # Never trust the caller-controlled X-User-Id header for secret ownership.
    owner_id = str(user.get("workspace_id", user.get("username", ""))).strip().lower()
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authenticated user is required")

    # Store credentials
    for cred in payload.credentials:
        vault.store(
            user_id=owner_id,
            sandbox_id=sandbox_id,
            key_name=cred.name,
            value=cred.source.value,
        )

    # Register bindings
    for binding in payload.bindings:
        vault.register_binding(sandbox_id, binding.model_dump())

    return {
        "sandbox_id": sandbox_id,
        "credentials_count": len(payload.credentials),
        "bindings_count": len(payload.bindings),
        "message": "Vault credentials and bindings created successfully.",
    }


@router.get(
    "/sandboxes/{sandbox_id}/vault/keys",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Sanitized list of secret key names (no values exposed)"},
    },
)
def list_vault_keys(
    request: Request,
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user: dict = Depends(get_current_user),
) -> dict:
    """List secret key names stored in Vault (secret values are NEVER returned)."""
    vault = getattr(request.app.state, "credential_vault", None)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": SandboxErrorCodes.UNKNOWN_ERROR, "message": "Credential Vault is not initialized."},
        )

    owner_id = str(user.get("workspace_id", user.get("username", ""))).strip().lower()
    keys = vault.list_keys(user_id=owner_id, sandbox_id=sandbox_id)
    return {"sandbox_id": sandbox_id, "keys": keys}
