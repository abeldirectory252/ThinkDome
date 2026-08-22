"""Regression tests for Docker startup failures and secure network isolation."""

import json
from pathlib import Path

from thinkdome.core.config import Settings
from thinkdome.core.error_codes import SandboxErrorCodes
from thinkdome.sandbox.executors.base import ExecRequest
from thinkdome.sandbox.executors.docker.python_executor import PythonDockerExecutor


_NETNS_ERROR = (
    '500 Server Error: Internal Server Error ('
    '"bind-mount /proc/1044816/ns/net -> '
    '/var/run/docker/netns/a65ffff87c4a: no such file or directory")'
)


class _StartFailsWithNetnsMount:
    def start(self):
        from docker.errors import APIError

        raise APIError(_NETNS_ERROR)

    def remove(self, force=False):
        pass


class _Containers:
    def __init__(self):
        self.create_calls = []

    def create(self, **config):
        self.create_calls.append(config)
        return _StartFailsWithNetnsMount()


class _Client:
    def __init__(self):
        self.containers = _Containers()


def test_netns_mount_failure_does_not_weaken_network_isolation():
    """A daemon netns failure must not retry with host or bridge networking."""
    executor = PythonDockerExecutor(Settings())
    executor.client = _Client()

    result = executor._execute_sync(ExecRequest(code="print('test')", caller_role="LLM"))

    assert result.exit_code == 1
    assert result.error_code == SandboxErrorCodes.DOCKER_NETNS_SETUP_FAILED
    assert "Docker could not create the sandbox network namespace" in result.stderr
    assert "before the container or its seccomp profile starts" in result.stderr
    assert len(executor.client.containers.create_calls) == 1
    assert executor.client.containers.create_calls[0]["network_mode"] == "none"


def test_seccomp_profile_allows_statx_needed_by_current_runc():
    """runc uses statx while safely reopening its exec FIFO during startup."""
    profile_path = Path(__file__).resolve().parents[1] / "security" / "seccomp.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    allowed = {
        syscall
        for rule in profile["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for syscall in rule["names"]
    }

    assert "statx" in allowed
