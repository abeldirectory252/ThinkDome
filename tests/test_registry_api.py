from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from thinkdome.control_plane.contracts import NodeCapacity, NodeHeartbeat
from thinkdome.control_plane.registry_api import create_registry_router


class FakeRegistry:
    def __init__(self):
        self.nodes = []

    def heartbeat(self, payload):
        self.nodes.append(payload)


def payload():
    return NodeHeartbeat(
        node_id="node-a",
        capacity=NodeCapacity(cpu_millis=4000, memory_bytes=8_000_000_000, pids=1000, sandboxes=0),
        orchestrator_version="test",
        observed_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_registry_api_requires_matching_node_identity():
    registry = FakeRegistry()
    app = FastAPI()
    app.include_router(create_registry_router(registry))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://control")

    missing = await client.post("/internal/control-plane/nodes/heartbeat", json=payload())
    assert missing.status_code == 401
    mismatch = await client.post(
        "/internal/control-plane/nodes/heartbeat",
        json=payload(),
        headers={"X-ThinkDome-Node-ID": "node-b"},
    )
    assert mismatch.status_code == 403
    accepted = await client.post(
        "/internal/control-plane/nodes/heartbeat",
        json=payload(),
        headers={"X-ThinkDome-Node-ID": "node-a"},
    )
    assert accepted.status_code == 200
    assert len(registry.nodes) == 1
    await client.aclose()
