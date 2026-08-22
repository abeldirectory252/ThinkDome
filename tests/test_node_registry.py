from types import SimpleNamespace

from thinkdome.control_plane.registry import NodeRegistry


class FakeNodeQuery:
    def __init__(self, nodes):
        self.nodes = nodes

    def all(self):
        return self.nodes


def test_registry_reconciles_expired_nodes_through_model_save(monkeypatch):
    saved = []
    expired = SimpleNamespace(state="ready", lease_expires_at=10, save=lambda: saved.append("expired"))
    current = SimpleNamespace(state="ready", lease_expires_at=100, save=lambda: saved.append("current"))

    from thinkdome.control_plane import registry
    monkeypatch.setattr(registry.ExecutionNode, "query", classmethod(lambda cls: FakeNodeQuery([expired, current])))

    changed = NodeRegistry(object()).reconcile_expired(now=50)
    assert changed == 1
    assert expired.state == "offline"
    assert saved == ["expired"]
