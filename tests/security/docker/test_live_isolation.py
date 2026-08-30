"""Bounded live probes for explicitly enabled test Docker infrastructure.

Run with ``RUN_DOCKER_SECURITY_LIVE=1`` and a disposable Docker daemon. These
probes use only synthetic canaries and never kill host/sibling processes.
"""

import os
import shutil
import subprocess
import uuid

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_SECURITY_LIVE") != "1" or shutil.which("docker") is None,
    reason="live Docker security tests require RUN_DOCKER_SECURITY_LIVE=1 and docker",
)


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=15, check=False)


def test_executor_container_has_no_socket_and_minimal_runtime_config():
    """Purpose: verify socket, privilege, capability, namespace and rootfs controls."""
    name = f"thinkdome-security-{uuid.uuid4().hex[:12]}"
    try:
        created = _docker(
            "run", "-d", "--name", name, "--network=none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit=20", "python:3.9-slim", "sleep", "10",
        )
        assert created.returncode == 0, created.stderr
        inspect = _docker("inspect", name)
        assert inspect.returncode == 0
        assert '"Privileged": false' in inspect.stdout
        assert '"NetworkMode": "none"' in inspect.stdout
        assert "/var/run/docker.sock" not in inspect.stdout
        assert "/run/docker.sock" not in inspect.stdout
    finally:
        _docker("rm", "-f", name)


def test_two_synthetic_sandboxes_cannot_reach_each_other():
    """Purpose: verify mandatory container-to-container network separation."""
    names = [f"thinkdome-security-{uuid.uuid4().hex[:12]}" for _ in range(2)]
    try:
        for name in names:
            result = _docker("run", "-d", "--name", name, "--network=none", "python:3.9-slim", "sleep", "10")
            assert result.returncode == 0, result.stderr
        for name in names:
            result = _docker("exec", name, "sh", "-c", "test ! -e /var/run/docker.sock && test ! -e /run/docker.sock")
            assert result.returncode == 0
    finally:
        for name in names:
            _docker("rm", "-f", name)
