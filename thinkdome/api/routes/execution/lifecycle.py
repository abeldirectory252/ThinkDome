"""FastAPI routes for Sandbox Lifecycle API (pause, resume, renew expiration).

Implements lifecycle endpoints matching OpenSandbox Lifecycle API specifications.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from thinkdome.core.error_codes import SandboxErrorCodes
from thinkdome.core.dependencies import get_current_user
from thinkdome.api.routes.execution.authorization import authorize_sandbox_access

router = APIRouter(tags=["Lifecycle"], dependencies=[Depends(get_current_user)])


class RenewExpirationRequest(BaseModel):
    """Request payload for renewing sandbox expiration."""
    expires_at: Optional[datetime] = Field(
        None,
        description="New absolute expiration timestamp (UTC ISO format). Must be in the future.",
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        description="Relative TTL from now in seconds.",
    )


class RenewExpirationResponse(BaseModel):
    """Response payload for sandbox expiration renewal."""
    sandbox_id: str
    expires_at: str
    message: str = "Expiration renewed successfully."


@router.post(
    "/sandboxes/{sandbox_id}/pause",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Pause operation accepted"},
        404: {"description": "Sandbox not found"},
        409: {"description": "Conflict with current state"},
    },
)
async def pause_sandbox(
    request: Request,
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user: dict = Depends(get_current_user),
) -> Response:
    """Pause execution of a running sandbox while retaining state."""
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    authorize_sandbox_access(request, sandbox_id, user)
    if not lifecycle_service:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.UNKNOWN_ERROR,
                "message": "Lifecycle service is not initialized.",
            },
        )
    await lifecycle_service.pause_sandbox(sandbox_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/sandboxes/{sandbox_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Resume operation accepted"},
        404: {"description": "Sandbox not found"},
        409: {"description": "Conflict with current state"},
    },
)
async def resume_sandbox(
    request: Request,
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user: dict = Depends(get_current_user),
) -> Response:
    """Resume execution of a paused sandbox."""
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    authorize_sandbox_access(request, sandbox_id, user)
    if not lifecycle_service:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.UNKNOWN_ERROR,
                "message": "Lifecycle service is not initialized.",
            },
        )
    await lifecycle_service.resume_sandbox(sandbox_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/sandboxes/{sandbox_id}/renew-expiration",
    response_model=RenewExpirationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Expiration updated successfully"},
        400: {"description": "Invalid parameter or expiration not in future"},
        404: {"description": "Sandbox not found"},
        409: {"description": "Sandbox in non-renewable state"},
    },
)
def renew_sandbox_expiration(
    request: Request,
    sandbox_id: str,
    payload: RenewExpirationRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user: dict = Depends(get_current_user),
) -> RenewExpirationResponse:
    """Renew absolute sandbox expiration time or relative TTL."""
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    authorize_sandbox_access(request, sandbox_id, user)
    if not lifecycle_service:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.UNKNOWN_ERROR,
                "message": "Lifecycle service is not initialized.",
            },
        )

    info = lifecycle_service.renew_expiration(
        sandbox_id=sandbox_id,
        expires_at=payload.expires_at,
        timeout_seconds=payload.timeout_seconds,
    )
    res_dict = lifecycle_service.sandbox_to_dict(info)
    return RenewExpirationResponse(
        sandbox_id=info.sandbox_id,
        expires_at=res_dict.get("expires_at", ""),
    )
