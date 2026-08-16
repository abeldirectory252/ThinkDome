"""FastAPI routes for Sandbox Metadata Management (JSON Merge Patch RFC 7396).

Enables updating/patching sandbox metadata labels with K8s-style label validation.
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request, status

from thinkdome.core.error_codes import SandboxErrorCodes

router = APIRouter(tags=["Metadata"])


@router.patch(
    "/sandboxes/{sandbox_id}/metadata",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Metadata patched successfully"},
        400: {"description": "Invalid label name/value or reserved prefix used"},
        404: {"description": "Sandbox not found"},
    },
)
def patch_sandbox_metadata(
    request: Request,
    sandbox_id: str,
    patch: Dict = Body(..., description="JSON Merge Patch object (key: value or key: null to delete)"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> dict:
    """Patch sandbox metadata via JSON Merge Patch (RFC 7396).

    Non-null adds/replaces, null deletes, absent keeps.
    Reserved label prefix 'thinkdome.io/' cannot be modified by user requests.
    """
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    if not lifecycle_service:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": SandboxErrorCodes.UNKNOWN_ERROR,
                "message": "Lifecycle service is not initialized.",
            },
        )

    info = lifecycle_service.patch_metadata(sandbox_id, patch)
    return lifecycle_service.sandbox_to_dict(info)
