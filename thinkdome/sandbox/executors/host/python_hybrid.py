"""Hybrid executor implementation for ThinkDome.

Dynamically routes execution requests between Docker (for low latency, standard tasks)
and Kubernetes (for high isolation, heavy tasks, or ADMIN executions).
"""

from __future__ import annotations

from typing import AsyncGenerator

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.sandbox.executors.docker import PythonDockerExecutor
from thinkdome.sandbox.executors.kubernetes import PythonKubernetesExecutor
from thinkdome.core.config import Settings


class PythonHybridExecutor(BaseExecutor):
    """Routes code executions to either Docker or Kubernetes depending on limits and roles."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.docker_exec = PythonDockerExecutor(settings)
        self.k8s_exec = PythonKubernetesExecutor(settings)

    async def initialize(self) -> None:
        """Initialize both backends."""
        try:
            await self.docker_exec.initialize()
        except Exception:
            pass  # Allow docker failure in non-docker envs
        try:
            await self.k8s_exec.initialize()
        except Exception:
            pass

    def set_pool_manager(self, pool_manager) -> None:
        """Propagate pool manager connection to docker executor."""
        self.docker_exec.set_pool_manager(pool_manager)

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Route task to correct executor based on memory limits and roles."""
        use_k8s = False
        if request.caller_role in ("ADMIN", "ORCH", "IDE"):
            use_k8s = True
        if request.memory_limit_mb and request.memory_limit_mb > 512:
            use_k8s = True

        if use_k8s:
            return await self.k8s_exec.execute(request)
        return await self.docker_exec.execute(request)

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Route streaming task to correct executor."""
        use_k8s = False
        if request.caller_role in ("ADMIN", "ORCH", "IDE"):
            use_k8s = True
        if request.memory_limit_mb and request.memory_limit_mb > 512:
            use_k8s = True

        if use_k8s:
            async for stream_type, chunk in self.k8s_exec.execute_stream(request):
                yield stream_type, chunk
        else:
            async for stream_type, chunk in self.docker_exec.execute_stream(request):
                yield stream_type, chunk

    async def shutdown(self) -> None:
        """Gracefully shut down both executors."""
        await self.docker_exec.shutdown()
        await self.k8s_exec.shutdown()

    async def health_check(self) -> bool:
        """Check status of active executors."""
        return await self.docker_exec.health_check() or await self.k8s_exec.health_check()
