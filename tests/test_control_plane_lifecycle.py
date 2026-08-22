from datetime import datetime, timezone
import pytest

from thinkdome.control_plane.contracts import NodeCapacity, NodeHeartbeat, SandboxPlacementRequest
from thinkdome.control_plane.lifecycle import ControlPlaneLifecycle, IdempotencyConflict


class FakeRepository:
    def __init__(self):
        self.keys = {}
        self.placements = []

    def get_idempotency(self, organization_id, operation, key):
        return self.keys.get((organization_id, operation, key))

    def save_placement(self, placement):
        self.placements.append(placement)

    def get_placement(self, sandbox_id):
        return next((item for item in self.placements if item.sandbox_id == sandbox_id), None)
        return placement

    def save_idempotency(self, organization_id, project_id, operation, key, resource_id, response):
        from types import SimpleNamespace
        item = SimpleNamespace(project_id=project_id, response_json=__import__('json').dumps(response))
        self.keys[(organization_id, operation, key)] = item
        return item


def node():
    return NodeHeartbeat(
        node_id="node-a",
        capacity=NodeCapacity(cpu_millis=4000, memory_bytes=8_000_000_000, pids=1000, sandboxes=0),
        orchestrator_version="test",
        observed_at=datetime.now(timezone.utc),
    )


def test_create_sandbox_is_idempotent():
    service = ControlPlaneLifecycle(FakeRepository())
    request = SandboxPlacementRequest(organization_id="org", project_id="project", sandbox_id="sb")
    first = service.create_sandbox(request, [node()], idempotency_key="request-1")
    second = service.create_sandbox(request, [node()], idempotency_key="request-1")
    assert first == second
    assert len(service.repository.placements) == 1


def test_sandbox_id_cannot_be_reallocated_with_new_key():
    service = ControlPlaneLifecycle(FakeRepository())
    request = SandboxPlacementRequest(organization_id="org", project_id="project", sandbox_id="sb")
    service.create_sandbox(request, [node()], idempotency_key="request-1")
    with pytest.raises(IdempotencyConflict, match="sandbox ID"):
        service.create_sandbox(request, [node()], idempotency_key="request-2")
