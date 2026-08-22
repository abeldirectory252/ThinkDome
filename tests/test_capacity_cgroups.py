from pathlib import Path

from thinkdome.control_plane.capacity import discover_capacity


def test_capacity_discovery_honors_cgroup_v2_limits(tmp_path: Path):
    (tmp_path / "cpu.max").write_text("50000 100000")
    (tmp_path / "memory.max").write_text("268435456")
    (tmp_path / "pids.max").write_text("128")

    capacity = discover_capacity(cgroup_root=tmp_path)
    assert capacity.cpu_millis <= 500
    assert capacity.memory_bytes == 268435456
    assert capacity.pids == 128
