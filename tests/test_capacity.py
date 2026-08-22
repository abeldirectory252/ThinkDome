from thinkdome.control_plane.capacity import discover_capacity


def test_capacity_discovery_returns_positive_admission_limits():
    capacity = discover_capacity(active_sandboxes=3)
    assert capacity.cpu_millis > 0
    assert capacity.memory_bytes > 0
    assert capacity.pids > 0
    assert capacity.sandboxes == 3
