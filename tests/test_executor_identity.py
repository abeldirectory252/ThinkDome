"""Regression tests for executor user identity consistency."""

import asyncio

from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.docker.backend import DockerBackend
from thinkdome.sandbox.executors.executor_backend import SandboxHandle


class _Container:
    def __init__(self):
        self.calls = []

    def exec_run(self, **kwargs):
        self.calls.append(kwargs)
        return type("Result", (), {"exit_code": 0, "output": b"ok"})()



class _Containers:
    def __init__(self, container):
        self.container = container

    def get(self, _container_id):
        return self.container


class _Client:
    def __init__(self, container):
        self.containers = _Containers(container)


def test_docker_exec_uses_image_sandbox_uid():
    container = _Container()
    backend = DockerBackend(Settings(), client=_Client(container))
    handle = SandboxHandle("sb-test", "container-test", "docker")

    result = asyncio.run(backend.execute_in_sandbox(handle, ["python3", "-c", "print(1)"]))

    assert result.exit_code == 0
    assert container.calls[0]["user"] == "1000:1000"
