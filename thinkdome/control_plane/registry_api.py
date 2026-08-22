"""Private control-plane API for node registration and heartbeats."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from thinkdome.control_plane.contracts import NodeHeartbeat
from thinkdome.control_plane.registry import NodeRegistry


def create_registry_router(registry: NodeRegistry) -> APIRouter:
    """Create the private node-registration router.

    The deployment must protect this router with mTLS. The node ID header is
    the identity extracted by the mTLS gateway; it is not user-controlled
    authorization.
    """
    router = APIRouter(prefix="/internal/control-plane", tags=["node-registry"])

    @router.post("/nodes/heartbeat")
    async def heartbeat(
        payload: NodeHeartbeat,
        node_identity: str | None = Header(default=None, alias="X-ThinkDome-Node-ID"),
    ):
        if not node_identity:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "NODE::IDENTITY_REQUIRED", "message": "node identity is required"},
            )
        if node_identity != payload.node_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "NODE::IDENTITY_MISMATCH", "message": "node identity does not match heartbeat"},
            )
        registry.heartbeat(payload)
        return {
            "status": "accepted",
            "node_id": payload.node_id,
            "lease_ttl_seconds": payload.lease_ttl_seconds,
        }

    return router
