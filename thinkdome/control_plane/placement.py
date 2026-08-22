"""Deterministic best-fit node placement for the control plane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from thinkdome.control_plane.contracts import (
    NodeHeartbeat,
    NodeState,
    SandboxPlacement,
    SandboxPlacementRequest,
)


class NoCapacityError(RuntimeError):
    """No healthy node can satisfy a sandbox placement request."""


def choose_node(
    request: SandboxPlacementRequest,
    nodes: Iterable[NodeHeartbeat],
    *,
    lease_seconds: int = 30,
) -> SandboxPlacement:
    """Choose the least-utilized healthy node in the requested region."""
    candidates = [
        node for node in nodes
        if node.state == NodeState.READY
        and (request.region is None or node.region == request.region)
        and node.capacity.can_fit(request)
    ]
    if not candidates:
        raise NoCapacityError(
            f"No ready node has capacity for sandbox {request.sandbox_id}"
        )

    selected = min(candidates, key=lambda node: (node.capacity.utilization_score(), node.node_id))
    return SandboxPlacement(
        sandbox_id=request.sandbox_id,
        node_id=selected.node_id,
        organization_id=request.organization_id,
        project_id=request.project_id,
        region=selected.region,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=lease_seconds),
    )
