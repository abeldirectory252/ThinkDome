"""Backend-neutral control-plane contracts.

These models deliberately contain no Docker or hypervisor objects. The API
uses them to schedule work; a node orchestrator translates them into local
runtime operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NodeState(str, Enum):
    REGISTERING = "registering"
    READY = "ready"
    DRAINING = "draining"
    OFFLINE = "offline"


class NodeCapacity(BaseModel):
    """Advertised and currently committed node resources."""

    cpu_millis: int = Field(gt=0)
    memory_bytes: int = Field(gt=0)
    pids: int = Field(gt=0)
    sandboxes: int = Field(ge=0)
    gpu_count: int = Field(default=0, ge=0)
    committed_cpu_millis: int = Field(default=0, ge=0)
    committed_memory_bytes: int = Field(default=0, ge=0)
    committed_pids: int = Field(default=0, ge=0)

    def can_fit(self, request: "SandboxPlacementRequest") -> bool:
        return (
            self.committed_cpu_millis + request.cpu_millis <= self.cpu_millis
            and self.committed_memory_bytes + request.memory_bytes <= self.memory_bytes
            and self.committed_pids + request.pids <= self.pids
            and request.gpu_count <= self.gpu_count
            and self.sandboxes < request.max_sandboxes_per_node
        )

    def utilization_score(self) -> float:
        ratios = (
            self.committed_cpu_millis / self.cpu_millis,
            self.committed_memory_bytes / self.memory_bytes,
            self.committed_pids / self.pids,
            self.sandboxes / max(1, self.sandboxes + 1),
        )
        return max(ratios)


class NodeHeartbeat(BaseModel):
    """Signed-registration payload exchanged by a node orchestrator."""

    node_id: str = Field(min_length=1, max_length=128)
    region: str = Field(default="default", min_length=1, max_length=64)
    state: NodeState = NodeState.READY
    capacity: NodeCapacity
    orchestrator_version: str = Field(min_length=1, max_length=128)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lease_ttl_seconds: int = Field(default=30, ge=5, le=300)


class SandboxPlacementRequest(BaseModel):
    """Resource and locality requirements for one tenant sandbox."""

    organization_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    sandbox_id: str = Field(min_length=1, max_length=128)
    cpu_millis: int = Field(default=500, gt=0)
    memory_bytes: int = Field(default=536_870_912, gt=0)
    pids: int = Field(default=64, gt=0)
    gpu_count: int = Field(default=0, ge=0)
    region: Optional[str] = Field(default=None, max_length=64)
    max_sandboxes_per_node: int = Field(default=100, gt=0)


class SandboxPlacement(BaseModel):
    """A durable placement decision returned by the scheduler."""

    sandbox_id: str
    node_id: str
    organization_id: str
    project_id: str
    region: str
    placement_version: int = Field(default=1, ge=1)
    lease_expires_at: datetime
