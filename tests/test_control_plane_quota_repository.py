from types import SimpleNamespace

import pytest

from thinkdome.control_plane.repository import ControlPlaneRepository


class FakeQuery:
    def __init__(self, item):
        self.item = item

    def filter(self, **kwargs):
        return self

    def first(self):
        return self.item

    def all(self):
        return self.item


def test_repository_reads_project_quota_from_orm(monkeypatch):
    from thinkdome.control_plane import repository
    project = SimpleNamespace(max_sandboxes=4, max_cpu_millis=2000, max_memory_bytes=1024)
    monkeypatch.setattr(repository.Project, "query", classmethod(lambda cls: FakeQuery(project)))
    quota = ControlPlaneRepository().get_project_quota("project")
    assert quota.max_sandboxes == 4
    assert quota.max_cpu_millis == 2000


def test_repository_rejects_cross_tenant_project(monkeypatch):
    from thinkdome.control_plane import repository

    project = SimpleNamespace(
        organization_id="org-a",
        status="active",
        max_sandboxes=4,
        max_cpu_millis=2000,
        max_memory_bytes=1024,
    )
    monkeypatch.setattr(repository.Project, "query", classmethod(lambda cls: FakeQuery(project)))
    with pytest.raises(ValueError, match="does not belong"):
        ControlPlaneRepository().get_project_quota("project", "org-b")


def test_reserve_sandbox_writes_usage_record(monkeypatch):
    from thinkdome.control_plane import repository
    from thinkdome.control_plane.contracts import SandboxPlacement, SandboxPlacementRequest
    from datetime import datetime, timezone

    saved = []

    class SandboxQuery(FakeQuery):
        def first(self):
            return None

    class FakeSandbox:
        @classmethod
        def query(cls):
            return SandboxQuery(None)

        def __init__(self, **values):
            self.__dict__.update(values)

        def save(self):
            saved.append(self)

    monkeypatch.setattr(repository.Sandbox, "query", classmethod(lambda cls: SandboxQuery(None)))
    monkeypatch.setattr(repository, "Sandbox", FakeSandbox)
    request = SandboxPlacementRequest(
        organization_id="org", project_id="project", sandbox_id="sb", cpu_millis=750,
        memory_bytes=128 * 1024 * 1024,
    )
    placement = SandboxPlacement(
        sandbox_id="sb", node_id="node", organization_id="org", project_id="project",
        region="default", lease_expires_at=datetime.now(timezone.utc),
    )
    ControlPlaneRepository().reserve_sandbox(request, placement)
    assert saved[0].status == "Provisioning"
    assert saved[0].cpu_limit == 0.75
    assert saved[0].memory_limit == 128


def test_transition_sandbox_enforces_tenant_and_state(monkeypatch):
    from thinkdome.control_plane import repository

    class Item:
        organization_id = "org"
        status = "Provisioning"
        placement_version = 3
        node_id = "node-a"

        def save(self):
            self.saved = True

    item = Item()
    monkeypatch.setattr(repository.Sandbox, "query", classmethod(lambda cls: FakeQuery(item)))
    result = ControlPlaneRepository().transition_sandbox(
        "sb", "org", "Running", expected_placement_version=3, node_id="node-b"
    )
    assert result.status == "Running"
    assert result.node_id == "node-b"
    assert result.saved is True

    with pytest.raises(repository.SandboxStateConflict, match="invalid sandbox transition"):
        ControlPlaneRepository().transition_sandbox("sb", "org", "Created")

    with pytest.raises(repository.SandboxStateConflict, match="does not belong"):
        ControlPlaneRepository().transition_sandbox("sb", "other", "Running")


def test_reserve_node_capacity_updates_committed_resources(monkeypatch):
    from thinkdome.control_plane import repository
    node = SimpleNamespace(
        capacity_json='{"cpu_millis":2000,"memory_bytes":1000,"pids":100,"gpu_count":1,"sandboxes":0}',
    )
    node.save = lambda: None
    monkeypatch.setattr(repository.ExecutionNode, "query", classmethod(lambda cls: FakeQuery(node)))
    from thinkdome.control_plane.contracts import SandboxPlacementRequest
    req = SandboxPlacementRequest(
        organization_id="org", project_id="project", sandbox_id="sb",
        cpu_millis=500, memory_bytes=400, pids=10,
    )
    ControlPlaneRepository().reserve_node_capacity("node", req)
    values = __import__("json").loads(node.capacity_json)
    assert values["committed_cpu_millis"] == 500
    assert values["committed_memory_bytes"] == 400
    assert values["sandboxes"] == 1


def test_release_sandbox_resources_never_underflows(monkeypatch):
    from thinkdome.control_plane import repository

    class SandboxItem:
        organization_id = "org"
        status = "Running"
        node_id = "node"
        cpu_limit = 0.5
        memory_limit = 128
        pids_limit = 10
        placement_version = 1

        def save(self):
            pass

    class Node:
        capacity_json = '{"committed_cpu_millis":100,"committed_memory_bytes":1,"committed_pids":2,"sandboxes":0}'

        def save(self):
            pass

    monkeypatch.setattr(repository.Sandbox, "query", classmethod(lambda cls: FakeQuery(SandboxItem())))
    monkeypatch.setattr(repository.ExecutionNode, "query", classmethod(lambda cls: FakeQuery(Node())))
    monkeypatch.setattr(repository.ControlPlaneRepository, "transition_sandbox", lambda self, *args, **kwargs: args and SandboxItem())
    result = ControlPlaneRepository().release_sandbox_resources("sb", "org")
    assert result is not None


def test_reconcile_expired_placements_reclaims_provisioning(monkeypatch):
    from thinkdome.control_plane import repository
    placement = SimpleNamespace(
        sandbox_id="sb", organization_id="org", lease_expires_at=1,
    )
    sandbox = SimpleNamespace(status="Provisioning")
    monkeypatch.setattr(repository.SandboxPlacement, "query", classmethod(lambda cls: FakeQuery([placement])))
    monkeypatch.setattr(repository.Sandbox, "query", classmethod(lambda cls: FakeQuery(sandbox)))
    calls = []
    monkeypatch.setattr(
        repository.ControlPlaneRepository,
        "release_sandbox_resources",
        lambda self, sandbox_id, organization_id, **kwargs: calls.append((sandbox_id, organization_id)),
    )
    assert ControlPlaneRepository().reconcile_expired_placements(now=2) == 1
    assert calls == [("sb", "org")]
