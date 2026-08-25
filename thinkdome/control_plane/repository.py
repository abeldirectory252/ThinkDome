"""ORM-backed control-plane persistence primitives."""

from __future__ import annotations

import json
import time
from typing import Optional
from sqlalchemy.exc import IntegrityError

from thinkdome.apps.sandbox.models import (
    ExecutionNode,
    Organization,
    Project,
    Sandbox,
    SandboxPlacement,
    IdempotencyRecord,
)
from thinkdome.control_plane.contracts import (
    NodeHeartbeat,
    NodeState,
    SandboxPlacement as PlacementContract,
    SandboxPlacementRequest,
)
from thinkdome.control_plane.quota import ProjectQuota, ProjectUsage


class SandboxStateConflict(ValueError):
    """A sandbox state update violates tenant or lifecycle concurrency rules."""


class ControlPlaneRepository:
    """Persists control-plane state through ThinkDome's custom ORM only."""

    def upsert_organization(self, organization_id: str, name: str) -> Organization:
        item = Organization.query().filter(organization_id=organization_id).first()
        if item:
            item.name = name
        else:
            item = Organization(organization_id=organization_id, name=name)
        item.save()
        return item

    def upsert_project(self, project_id: str, organization_id: str, name: str) -> Project:
        item = Project.query().filter(project_id=project_id).first()
        if item:
            if item.organization_id != organization_id:
                raise ValueError("project cannot move between organizations")
            item.name = name
        else:
            item = Project(project_id=project_id, organization_id=organization_id, name=name)
        item.save()
        return item

    def get_project_quota(
        self, project_id: str, organization_id: str | None = None
    ) -> ProjectQuota:
        project = Project.query().filter(project_id=project_id).first()
        if not project:
            raise ValueError(f"project '{project_id}' does not exist")
        if organization_id is not None and project.organization_id != organization_id:
            raise ValueError("project does not belong to organization")
        if getattr(project, "status", "active") != "active":
            raise ValueError("project is not active")
        if organization_id is not None:
            organization = Organization.query().filter(
                organization_id=project.organization_id
            ).first()
            if organization and getattr(organization, "status", "active") != "active":
                raise ValueError("organization is not active")
        return ProjectQuota(
            max_sandboxes=project.max_sandboxes,
            max_cpu_millis=project.max_cpu_millis,
            max_memory_bytes=project.max_memory_bytes,
        )

    def get_project_usage(self, organization_id: str, project_id: str) -> ProjectUsage:
        sandboxes = Sandbox.query().filter(
            organization_id=organization_id,
            project_id=project_id,
        ).all()
        active = [item for item in sandboxes if item.status not in ("Destroyed", "Terminated", "Stopped")]
        return ProjectUsage(
            sandboxes=len(active),
            cpu_millis=sum(int(item.cpu_limit * 1000) for item in active),
            memory_bytes=sum(int(item.memory_limit * 1024 * 1024) for item in active),
        )

    def record_heartbeat(self, heartbeat: NodeHeartbeat) -> ExecutionNode:
        item = ExecutionNode.query().filter(node_id=heartbeat.node_id).first()
        values = {
            "node_id": heartbeat.node_id,
            "region": heartbeat.region,
            "state": heartbeat.state.value,
            "capacity_json": heartbeat.capacity.model_dump_json(),
            "orchestrator_version": heartbeat.orchestrator_version,
            "lease_expires_at": time.time() + heartbeat.lease_ttl_seconds,
        }
        if item:
            for key, value in values.items():
                setattr(item, key, value)
        else:
            item = ExecutionNode(**values)
        item.save()
        return item

    def get_ready_heartbeats(self) -> list[NodeHeartbeat]:
        now = time.time()
        nodes = ExecutionNode.query().filter(state=NodeState.READY.value).all()
        result = []
        for node in nodes:
            if node.lease_expires_at <= now:
                continue
            result.append(NodeHeartbeat(
                node_id=node.node_id,
                region=node.region,
                state=NodeState(node.state),
                capacity=json.loads(node.capacity_json or "{}"),
                orchestrator_version=node.orchestrator_version,
                lease_ttl_seconds=max(5, int(node.lease_expires_at - now)),
            ))
        return result

    def save_placement(self, placement: PlacementContract) -> SandboxPlacement:
        existing = SandboxPlacement.query().filter(sandbox_id=placement.sandbox_id).first()
        values = placement.model_dump()
        values["lease_expires_at"] = placement.lease_expires_at.timestamp()
        if existing:
            if existing.organization_id != placement.organization_id or existing.project_id != placement.project_id:
                raise ValueError("sandbox placement tenant scope cannot change")
            for key, value in values.items():
                if key != "sandbox_id":
                    setattr(existing, key, value)
            existing.save()
            return existing
        item = SandboxPlacement(**values)
        item.save()
        return item

    def get_placement(self, sandbox_id: str) -> SandboxPlacement | None:
        return SandboxPlacement.query().filter(sandbox_id=sandbox_id).first()

    def reserve_sandbox(self, request, placement: PlacementContract) -> Sandbox:
        """Create the ORM usage record associated with a placement reservation."""
        item = Sandbox.query().filter(id=placement.sandbox_id).first()
        if item:
            if item.organization_id != request.organization_id or item.project_id != request.project_id:
                raise ValueError("sandbox tenant scope cannot change")
            item.node_id = placement.node_id
            item.placement_version = placement.placement_version
            item.status = "Provisioning"
        else:
            item = Sandbox(
                id=placement.sandbox_id,
                name=placement.sandbox_id,
                owner=request.organization_id,
                organization_id=request.organization_id,
                project_id=request.project_id,
                node_id=placement.node_id,
                placement_version=placement.placement_version,
                status="Provisioning",
                cpu_limit=request.cpu_millis / 1000,
                memory_limit=max(1, request.memory_bytes // (1024 * 1024)),
                pids_limit=request.pids,
                gpu_limit=request.gpu_count,
                network_enabled=False,
            )
        item.save()
        return item

    def reserve_node_capacity(
        self, node_id: str, request: SandboxPlacementRequest
    ) -> ExecutionNode:
        """Persist the resource commitment made by a placement decision."""
        node = ExecutionNode.query().filter(node_id=node_id).first()
        if not node:
            raise ValueError("placement node is no longer registered")
        capacity = json.loads(node.capacity_json or "{}")
        if (
            capacity.get("committed_cpu_millis", 0) + request.cpu_millis > capacity.get("cpu_millis", 0)
            or capacity.get("committed_memory_bytes", 0) + request.memory_bytes > capacity.get("memory_bytes", 0)
            or capacity.get("committed_pids", 0) + request.pids > capacity.get("pids", 0)
            or request.gpu_count > capacity.get("gpu_count", 0)
        ):
            raise ValueError("node capacity changed before reservation")
        capacity["committed_cpu_millis"] = capacity.get("committed_cpu_millis", 0) + request.cpu_millis
        capacity["committed_memory_bytes"] = capacity.get("committed_memory_bytes", 0) + request.memory_bytes
        capacity["committed_pids"] = capacity.get("committed_pids", 0) + request.pids
        capacity["sandboxes"] = capacity.get("sandboxes", 0) + 1
        node.capacity_json = json.dumps(capacity, separators=(",", ":"))
        node.save()
        return node

    def release_node_capacity(self, node_id: str, request: SandboxPlacementRequest) -> None:
        """Undo a reservation made by a losing idempotency race."""
        node = ExecutionNode.query().filter(node_id=node_id).first()
        if not node:
            return
        capacity = json.loads(node.capacity_json or "{}")
        capacity["committed_cpu_millis"] = max(0, capacity.get("committed_cpu_millis", 0) - request.cpu_millis)
        capacity["committed_memory_bytes"] = max(0, capacity.get("committed_memory_bytes", 0) - request.memory_bytes)
        capacity["committed_pids"] = max(0, capacity.get("committed_pids", 0) - request.pids)
        capacity["sandboxes"] = max(0, capacity.get("sandboxes", 0) - 1)
        node.capacity_json = json.dumps(capacity, separators=(",", ":"))
        node.save()

    def release_sandbox_resources(
        self, sandbox_id: str, organization_id: str, *, target_status: str = "Destroyed"
    ) -> Sandbox:
        """Release a sandbox's node commitment and transition its state."""
        item = Sandbox.query().filter(id=sandbox_id).first()
        if not item:
            raise SandboxStateConflict("sandbox does not exist")
        if item.organization_id != organization_id:
            raise SandboxStateConflict("sandbox does not belong to organization")
        if item.status in ("Stopped", "Destroyed"):
            return self.transition_sandbox(sandbox_id, organization_id, target_status)

        node = ExecutionNode.query().filter(node_id=item.node_id).first()
        if node:
            capacity = json.loads(node.capacity_json or "{}")
            cpu = int(float(item.cpu_limit) * 1000)
            memory = int(item.memory_limit) * 1024 * 1024
            capacity["committed_cpu_millis"] = max(
                0, capacity.get("committed_cpu_millis", 0) - cpu
            )
            capacity["committed_memory_bytes"] = max(
                0, capacity.get("committed_memory_bytes", 0) - memory
            )
            capacity["committed_pids"] = max(
                0, capacity.get("committed_pids", 0) - int(getattr(item, "pids_limit", 64))
            )
            capacity["sandboxes"] = max(0, capacity.get("sandboxes", 0) - 1)
            node.capacity_json = json.dumps(capacity, separators=(",", ":"))
            node.save()
        return self.transition_sandbox(sandbox_id, organization_id, target_status)

    def reconcile_expired_placements(self, now: float | None = None) -> int:
        """Reclaim provisioning reservations whose placement lease expired."""
        current = time.time() if now is None else now
        reclaimed = 0
        for placement in SandboxPlacement.query().all():
            if placement.lease_expires_at > current:
                continue
            sandbox = Sandbox.query().filter(id=placement.sandbox_id).first()
            if not sandbox or sandbox.status not in ("Created", "Provisioning"):
                continue
            try:
                self.release_sandbox_resources(
                    placement.sandbox_id,
                    placement.organization_id,
                    target_status="Destroyed",
                )
                reclaimed += 1
            except SandboxStateConflict:
                continue
        return reclaimed

    def transition_sandbox(
        self,
        sandbox_id: str,
        organization_id: str,
        target_status: str,
        *,
        expected_placement_version: int | None = None,
        node_id: str | None = None,
    ) -> Sandbox:
        """Apply a valid tenant-scoped lifecycle transition."""
        allowed = {
            "Created": {"Provisioning", "Destroyed"},
            "Provisioning": {"Running", "Stopped", "Destroyed"},
            "Running": {"Paused", "Stopped", "Destroyed"},
            "Paused": {"Running", "Stopped", "Destroyed"},
            "Stopped": {"Destroyed"},
            "Destroyed": set(),
        }
        if target_status not in allowed:
            raise SandboxStateConflict(f"unknown sandbox state '{target_status}'")
        item = Sandbox.query().filter(id=sandbox_id).first()
        if not item:
            raise SandboxStateConflict("sandbox does not exist")
        if item.organization_id != organization_id:
            raise SandboxStateConflict("sandbox does not belong to organization")
        if expected_placement_version is not None and item.placement_version != expected_placement_version:
            raise SandboxStateConflict("sandbox placement version changed")
        if target_status != item.status and target_status not in allowed.get(item.status, set()):
            raise SandboxStateConflict(
                f"invalid sandbox transition {item.status} -> {target_status}"
            )
        if node_id is not None:
            item.node_id = node_id
        item.status = target_status
        item.save()
        return item

    def get_idempotency(self, organization_id: str, operation: str, key: str) -> Optional[IdempotencyRecord]:
        """Return an unexpired operation record for safe request replay."""
        item = IdempotencyRecord.query().filter(
            organization_id=organization_id,
            operation=operation,
            idempotency_key=key,
        ).first()
        if item and item.expires_at > time.time():
            return item
        return None

    def save_idempotency(
        self,
        organization_id: str,
        project_id: str,
        operation: str,
        key: str,
        resource_id: str,
        response: dict,
        ttl_seconds: int = 86_400,
    ) -> IdempotencyRecord:
        """Persist the result of a completed operation through the ORM."""
        item = IdempotencyRecord(
            organization_id=organization_id,
            project_id=project_id,
            idempotency_key=key,
            operation=operation,
            resource_id=resource_id,
            response_json=json.dumps(response, separators=(",", ":")),
            expires_at=time.time() + ttl_seconds,
        )
        try:
            item.save()
            item._created_by_call = True
            return item
        except IntegrityError:
            # Another worker won the insert race. Re-read the committed result
            # and let the caller replay it rather than surfacing a 500.
            from thinkdome.core.orm.orm import _get_active_db
            _get_active_db().rollback()
            existing = self.get_idempotency(organization_id, operation, key)
            if existing and existing.project_id == project_id:
                existing._created_by_call = False
                return existing
            raise
