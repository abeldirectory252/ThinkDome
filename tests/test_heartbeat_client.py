from datetime import datetime, timezone

import httpx
import pytest

from thinkdome.control_plane.contracts import NodeCapacity, NodeHeartbeat
from thinkdome.control_plane.heartbeat_client import NodeHeartbeatClient


def heartbeat():
    return NodeHeartbeat(
        node_id="node-a",
        capacity=NodeCapacity(cpu_millis=4000, memory_bytes=8_000_000_000, pids=1000, sandboxes=0),
        orchestrator_version="test",
        observed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_heartbeat_client_publishes_identity_header():
    seen = {}

    async def handler(request):
        seen["identity"] = request.headers["X-ThinkDome-Node-ID"]
        return httpx.Response(200, json={"status": "accepted"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    publisher = NodeHeartbeatClient("http://control", "node-a", heartbeat, client=client)
    result = await publisher.publish_once()
    await client.aclose()

    assert result["status"] == "accepted"
    assert seen["identity"] == "node-a"
