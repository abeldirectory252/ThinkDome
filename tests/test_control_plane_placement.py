from datetime import datetime, timezone

import pytest

from thinkdome.control_plane.contracts import (
    NodeCapacity,
    NodeHeartbeat,
    NodeState,
    SandboxPlacementRequest,
)
from thinkdome.control_plane.placement import NoCapacityError, choose_node


def _node(node_id: str, committed: int, region: str = "eu") -> NodeHeartbeat:
    return NodeHeartbeat(
        node_id=node_id,
        region=region,
        capacity=NodeCapacity(
            cpu_millis=4000,
            memory_bytes=8_000_000_000,
            pids=1000,
            sandboxes=committed,
            committed_cpu_millis=committed * 500,
            committed_memory_bytes=committed * 500_000_000,
            committed_pids=committed * 64,
        ),
        orchestrator_version="test",
        observed_at=datetime.now(timezone.utc),
    )


def test_choose_node_prefers_least_utilized_ready_node():
    request = SandboxPlacementRequest(
        organization_id="org_1", project_id="proj_1", sandbox_id="sb_1", region="eu"
    )
    placement = choose_node(request, [_node("busy", 4), _node("free", 1)])
    assert placement.node_id == "free"
    assert placement.organization_id == "org_1"


def test_choose_node_rejects_wrong_region_and_unhealthy_nodes():
    request = SandboxPlacementRequest(
        organization_id="org_1", project_id="proj_1", sandbox_id="sb_1", region="us"
    )
    draining = _node("draining", 0, "us")
    draining.state = NodeState.DRAINING
    with pytest.raises(NoCapacityError):
        choose_node(request, [_node("eu", 0), draining])
