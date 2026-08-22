"""Best-effort host capacity discovery for execution-node heartbeats."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from thinkdome.control_plane.contracts import NodeCapacity


def _memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 512 * 1024 * 1024


def _cgroup_limit(root: Path, filename: str) -> Optional[int]:
    try:
        value = (root / filename).read_text().strip()
        if value == "max":
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (OSError, ValueError):
        return None


def _cgroup_cpu_millis(root: Path) -> Optional[int]:
    try:
        quota, period = (root / "cpu.max").read_text().split()[:2]
        if quota == "max":
            return None
        return max(1, int(int(quota) * 1000 / int(period)))
    except (OSError, ValueError, IndexError, ZeroDivisionError):
        return None


def _pid_capacity() -> int:
    try:
        value = Path("/proc/sys/kernel/pid_max").read_text().strip()
        return max(1, int(value))
    except (OSError, ValueError):
        return 32_768


def discover_capacity(
    active_sandboxes: int = 0,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> NodeCapacity:
    """Return conservative host capacity suitable for scheduler admission."""
    cpu_count = max(1, os.cpu_count() or 1)
    cpu_millis = _cgroup_cpu_millis(cgroup_root) or cpu_count * 1000
    memory_bytes = _cgroup_limit(cgroup_root, "memory.max") or _memory_bytes()
    pids = _cgroup_limit(cgroup_root, "pids.max") or _pid_capacity()
    return NodeCapacity(
        cpu_millis=min(cpu_count * 1000, cpu_millis),
        memory_bytes=memory_bytes,
        pids=pids,
        sandboxes=max(0, active_sandboxes),
    )
