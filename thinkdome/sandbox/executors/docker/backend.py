"""Docker executor backend implementation for ThinkDome.

Implements safe, isolated execution using local Docker engine or DinD sidecars.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import docker
from thinkdome.sandbox.executors.executor_backend import (
    BackendHealth,
    ExecutionResult,
    ExecutorBackend,
    SandboxHandle,
)
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)


class DockerBackend(ExecutorBackend):
    """Docker-based execution sandbox backend."""

    def __init__(self, settings: Settings, client: Optional[docker.DockerClient] = None) -> None:
        self.settings = settings
        self.client = client
        from thinkdome.core.config import get_workspace_root
        self.seccomp_path = str(get_workspace_root() / "security" / "seccomp.json")

    async def create_sandbox(
        self,
        sandbox_id: str,
        memory_mb: int,
        cpu_cores: float,
        network_enabled: bool,
        gpu_count: int = 0,
    ) -> SandboxHandle:
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        # Load seccomp profile
        seccomp_profile = None
        if os.path.exists(self.seccomp_path):
            try:
                with open(self.seccomp_path, "r") as f:
                    seccomp_profile = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load seccomp.json: {e}")

        # Construct host config security opt
        security_opt = ["no-new-privileges:true"]
        if seccomp_profile:
            security_opt.append(f"seccomp={json.dumps(seccomp_profile)}")

        device_requests = []
        if gpu_count > 0:
            device_requests.append(
                docker.types.DeviceRequest(count=gpu_count, capabilities=[["gpu"]])
            )

        loop = asyncio.get_event_loop()

        def _create():
            container = self.client.containers.run(
                image=self.settings.EXECUTOR_IMAGE,
                command=["sleep", "infinity"],
                detach=True,
                name=f"thinkdome-sb-{sandbox_id}",
                mem_limit=f"{memory_mb}m",
                memswap_limit=f"{memory_mb}m",
                nano_cpus=int(cpu_cores * 1e9),
                user="1000:1000",
                read_only=True,
                tmpfs={
                    "/tmp": "size=67108864,noexec,nosuid,nodev",
                    "/workspace": "size=67108864,nosuid,nodev",
                },
                cap_drop=["ALL"],
                security_opt=security_opt,
                network_mode="none" if not network_enabled else "bridge",
                device_requests=device_requests,
                init=True,
            )
            return container

        container = await loop.run_in_executor(None, _create)
        return SandboxHandle(
            sandbox_id=sandbox_id,
            container_id=container.id,
            backend_type="docker",
            metadata={"name": container.name},
        )

    async def execute_in_sandbox(
        self,
        handle: SandboxHandle,
        command: list[str],
        user: str = "sandboxuser",
        env_vars: Optional[Dict[str, str]] = None,
        timeout_ms: int = 10000,
    ) -> ExecutionResult:
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        loop = asyncio.get_event_loop()
        start = time.perf_counter()

        def _exec():
            container = self.client.containers.get(handle.container_id)
            res = container.exec_run(
                cmd=command,
                user=user,
                environment=env_vars,
                workdir="/workspace",
            )
            return res.exit_code, res.output

        try:
            exit_code, output = await asyncio.wait_for(
                loop.run_in_executor(None, _exec),
                timeout=timeout_ms / 1000.0,
            )
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                stdout=output.decode("utf-8", errors="ignore"),
                stderr="",
                exit_code=exit_code,
                timed_out=False,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                stdout="",
                stderr="Execution timed out.",
                exit_code=-1,
                timed_out=True,
                duration_ms=duration_ms,
            )

    async def destroy_sandbox(self, handle: SandboxHandle) -> None:
        if not self.client:
            return

        loop = asyncio.get_event_loop()

        def _destroy():
            try:
                container = self.client.containers.get(handle.container_id)
                container.remove(force=True)
            except Exception:
                pass

        await loop.run_in_executor(None, _destroy)

    async def health_check(self) -> BackendHealth:
        if not self.client:
            return BackendHealth(status="unhealthy", details={"error": "Client not initialized"})

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self.client.ping)
            return BackendHealth(status="healthy", details={"client": "connected"})
        except Exception as e:
            return BackendHealth(status="unhealthy", details={"error": str(e)})
