"""Tenant-scoped placement endpoints for the distributed control plane."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from thinkdome.control_plane.contracts import SandboxPlacementRequest
from thinkdome.control_plane.lifecycle import ControlPlaneLifecycle, IdempotencyConflict
from thinkdome.control_plane.placement import NoCapacityError
from thinkdome.core.dependencies import (
    get_control_plane_lifecycle,
    get_current_admin,
    get_current_user,
)
from thinkdome.core.error_codes import SandboxErrorCodes

router = APIRouter(prefix="/control-plane", tags=["control-plane"])


class PlacementRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    sandbox_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    cpu_millis: int = Field(default=500, gt=0, le=256_000)
    memory_bytes: int = Field(default=536_870_912, gt=0, le=68_719_476_736)
    pids: int = Field(default=64, gt=0, le=4096)
    gpu_count: int = Field(default=0, ge=0, le=16)
    region: str | None = Field(default=None, max_length=64)


class StateTransitionRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    expected_placement_version: int | None = Field(default=None, ge=1)
    node_id: str | None = Field(default=None, max_length=128)


@router.get("/nodes")
async def list_ready_nodes(
    current_user: dict = Depends(get_current_admin),
    lifecycle: ControlPlaneLifecycle = Depends(get_control_plane_lifecycle),
):
    """Return live node capacity for the operator console."""
    # Node heartbeats are optional in local/offline deployments.  A missing or
    # not-yet-initialized ORM table must not turn the dashboard status widget
    # into a 500 response.
    try:
        nodes = lifecycle.repository.get_ready_heartbeats()
    except Exception:
        nodes = []
    return {"nodes": [node.model_dump(mode="json") for node in nodes]}


@router.post("/placements", status_code=status.HTTP_201_CREATED)
async def create_placement(
    request: PlacementRequest,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(get_current_user),
    lifecycle: ControlPlaneLifecycle = Depends(get_control_plane_lifecycle),
):
    """Reserve a sandbox on a live node before runtime provisioning."""
    claimed_org = current_user.get("organization_id")
    role = str(current_user.get("role", "")).upper()
    from thinkdome.security.identity.core import is_admin_role
    if not claimed_org and not is_admin_role(role):
        raise HTTPException(
            status_code=403,
            detail={
                "code": SandboxErrorCodes.TENANT_CONTEXT_REQUIRED,
                "message": "authenticated tenant context is required",
            },
        )
    organization_id = organization_id or claimed_org
    if not organization_id:
        raise HTTPException(
            status_code=400,
            detail={"code": SandboxErrorCodes.INVALID_PARAMETER, "message": "X-Organization-ID is required"},
        )
    if claimed_org and claimed_org != organization_id and role not in admin_roles:
        raise HTTPException(
            status_code=403,
            detail={"code": SandboxErrorCodes.TENANT_SCOPE_DENIED, "message": "organization scope does not match token"},
        )
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=400,
            detail={"code": SandboxErrorCodes.INVALID_PARAMETER, "message": "Idempotency-Key is required"},
        )

    placement_request = SandboxPlacementRequest(
        organization_id=organization_id,
        project_id=request.project_id,
        sandbox_id=request.sandbox_id,
        cpu_millis=request.cpu_millis,
        memory_bytes=request.memory_bytes,
        pids=request.pids,
        gpu_count=request.gpu_count,
        region=request.region,
    )
    try:
        result = lifecycle.create_sandbox(
            placement_request,
            lifecycle.repository.get_ready_heartbeats(),
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": SandboxErrorCodes.IDEMPOTENCY_CONFLICT, "message": str(exc)},
        ) from exc
    except NoCapacityError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": SandboxErrorCodes.NO_NODE_CAPACITY, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": SandboxErrorCodes.INVALID_PARAMETER, "message": str(exc)},
        ) from exc
    return result.__dict__


@router.post("/sandboxes/{sandbox_id}/state")
async def transition_sandbox_state(
    sandbox_id: str,
    request: StateTransitionRequest,
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
    current_user: dict = Depends(get_current_admin),
    lifecycle: ControlPlaneLifecycle = Depends(get_control_plane_lifecycle),
):
    """Apply a node/control-plane lifecycle acknowledgement."""
    organization_id = organization_id or current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=400,
            detail={"code": SandboxErrorCodes.INVALID_PARAMETER, "message": "X-Organization-ID is required"},
        )
    if current_user.get("organization_id") and current_user["organization_id"] != organization_id:
        raise HTTPException(
            status_code=403,
            detail={"code": SandboxErrorCodes.TENANT_SCOPE_DENIED, "message": "organization scope does not match token"},
        )
    try:
        item = lifecycle.repository.transition_sandbox(
            sandbox_id,
            organization_id,
            request.status,
            expected_placement_version=request.expected_placement_version,
            node_id=request.node_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": SandboxErrorCodes.STATE_CONFLICT, "message": str(exc)},
        ) from exc
    return {
        "sandbox_id": sandbox_id,
        "organization_id": organization_id,
        "status": item.status,
        "node_id": item.node_id,
        "placement_version": item.placement_version,
    }
