"""Docker executor backend implementation for ThinkDome.

Implements safe, isolated execution using local Docker engine or DinD sidecars.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import threading
from typing import Any, Dict, Optional

import docker
from thinkdome.sandbox.executors.executor_backend import (
    BackendHealth,
    ExecutionResult,
    ExecutorBackend,
    SandboxHandle,
)
from thinkdome.core.config import Settings
from thinkdome.sandbox.network.docker_policy import DockerSandboxPolicy
from thinkdome.sandbox.executors.docker.container_policy import DockerContainerPolicy, DockerExecutionPolicy
from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup

logger = logging.getLogger(__name__)


from thinkdome.sandbox.executors.docker.client import DockerExecutorClient, DockerClientShim

class DockerBackend(ExecutorBackend):
    """Docker-based execution sandbox backend."""

    def __init__(self, settings: Settings, client: Optional[Any] = None) -> None:
        self.settings = settings
        if settings.EXECUTOR_CONTROL_URL or isinstance(client, (DockerExecutorClient, DockerClientShim)):
            if isinstance(client, DockerClientShim):
                self.remote_client = client.executor_client
                self.client = client
            elif isinstance(client, DockerExecutorClient):
                self.remote_client = client
                self.client = DockerClientShim(client)
            else:
                self.remote_client = DockerExecutorClient(settings)
                self.client = DockerClientShim(self.remote_client)
        else:
            self.remote_client = None
            self.client = client
        self.network_policy = DockerSandboxPolicy(self.client) if self.client else None
        self._runtime_validation_lock = threading.Lock()
        self._runtime_validated = False

    def _ensure_runtime_validated(self) -> None:
        if self._runtime_validated:
            return
        with self._runtime_validation_lock:
            if self._runtime_validated:
                return
            self.settings.validate_production_runtime()
            validate_secure_runtime_on_startup(self.settings, docker_client=self.client)
            self._runtime_validated = True
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
        if self.remote_client:
            return await self.remote_client.create_sandbox(
                sandbox_id=sandbox_id,
                memory_mb=memory_mb,
                cpu_cores=cpu_cores,
                network_enabled=network_enabled,
                gpu_count=gpu_count,
            )

        if not self.client:
            raise RuntimeError("Docker client not initialized")
        DockerSandboxPolicy.validate_resources(sandbox_id, memory_mb, cpu_cores, gpu_count)

        self._ensure_runtime_validated()
        runtime = DockerContainerPolicy.runtime(self.settings)

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

        attachment = self.network_policy.attachment(network_enabled)

        loop = asyncio.get_event_loop()

        def _create():
            container = self.client.containers.run(
                image=self.settings.EXECUTOR_IMAGE,
                command=["sleep", "infinity"],
                detach=True,
                name=f"thinkdome-sb-{sandbox_id}",
                labels={
                    "thinkdome.sandbox_id": sandbox_id,
                    "thinkdome.security_profile": "restricted",
                },
                mem_limit=f"{memory_mb}m",
                memswap_limit=f"{memory_mb}m",
                nano_cpus=int(cpu_cores * 1e9),
                user="1000:1000",  # Sandbox execution user is fixed
                read_only=True,
                tmpfs={
                    "/tmp": f"size={DockerContainerPolicy._bounded_size(self.settings, 'SANDBOX_TMPFS_SIZE_MB', 64, 4096)}m,noexec,nosuid,nodev,mode=1777",
                    "/workspace": f"size={DockerContainerPolicy._bounded_size(self.settings, 'SANDBOX_TMPFS_SIZE_MB', 64, 4096)}m,noexec,nosuid,nodev,mode=1777",
                },
                cap_drop=["ALL"],
                privileged=False,
                security_opt=security_opt,
                pids_limit=100,
                ipc_mode="private",
                shm_size=DockerContainerPolicy.shm_size(self.settings),
                ulimits=DockerContainerPolicy.nofile_ulimit(self.settings),
                network_mode=attachment.mode,
                environment=attachment.environment,
                runtime=runtime,
                device_requests=device_requests,
                init=True,
            )
            return container

        container = await loop.run_in_executor(None, _create)
        return SandboxHandle(
            sandbox_id=sandbox_id,
            container_id=container.id,
            backend_type="docker",
            metadata={"name": container.name, "network_mode": attachment.mode},
        )

    async def execute_in_sandbox(
        self,
        handle: SandboxHandle,
        command: list[str],
        # The executor image creates UID/GID 1000 as ``sandbox``.  Using the
        # old ``sandboxuser`` name makes Docker exec fail with "no such user"
        # on the shipped image and turns every execution into an error.
        user: str = "1000:1000",
        env_vars: Optional[Dict[str, str]] = None,
        timeout_ms: int = 10000,
    ) -> ExecutionResult:
        if self.remote_client:
            return await self.remote_client.execute_in_sandbox(
                handle=handle,
                command=command,
                user=user,
                env_vars=env_vars,
                timeout_ms=timeout_ms,
            )

        if not self.client:
            raise RuntimeError("Docker client not initialized")
        if not handle.metadata or handle.metadata.get("destroyed"):
            raise RuntimeError("Sandbox handle is no longer active")
        # effective_timeout_ms = min
        effective_timeout_ms = DockerSandboxPolicy.validate_execution(
            command, user, timeout_ms, int(self.settings.MAX_EXEC_TIMEOUT_MS)
        )

        loop = asyncio.get_event_loop()
        start = time.perf_counter()

        def _exec():
            container = self.client.containers.get(handle.container_id)
            labels = (container.attrs.get("Config") or {}).get("Labels") or {}
            if labels.get("thinkdome.sandbox_id") != handle.sandbox_id:
                raise RuntimeError("Sandbox container ownership does not match its handle")
            actual_mode = str(
                (container.attrs.get("HostConfig") or {}).get("NetworkMode", "none")
            )
            recorded_mode = str(handle.metadata.get("network_mode", "none"))
            if actual_mode != recorded_mode:
                raise RuntimeError("Sandbox network configuration does not match its handle")
            if actual_mode not in {"none", DockerSandboxPolicy.PROXY_NETWORK}:
                raise RuntimeError("Sandbox is attached to an unauthorized Docker network")
            network_mode = actual_mode
            execution_env = DockerExecutionPolicy.sanitize_environment(dict(env_vars or {}))
            execution_env = self.network_policy.enforce_environment(execution_env, network_mode)
            execution_env["PATH"] = DockerExecutionPolicy.SAFE_PATH
            res = container.exec_run(
                cmd=command,
                user=user,
                environment=execution_env,
                workdir="/workspace",
            )
            return res.exit_code, res.output

        try:
            exit_code, output = await asyncio.wait_for(
                loop.run_in_executor(None, _exec),
                timeout=effective_timeout_ms / 1000.0,
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
            # ``exec_run`` blocks in the Docker SDK thread and cannot be
            # cancelled safely. Kill the sandbox so a timed-out command
            # cannot continue consuming CPU after the API reports timeout.
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._terminate_container(handle.container_id),
                )
            except Exception as kill_error:
                logger.warning(
                    "Failed to terminate timed-out sandbox %s: %s",
                    handle.sandbox_id,
                    kill_error,
                )
            handle.metadata["destroyed"] = True
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                stdout="",
                stderr="Execution timed out.",
                exit_code=-1,
                timed_out=True,
                duration_ms=duration_ms,
            )

    async def destroy_sandbox(self, handle: SandboxHandle) -> None:
        if self.remote_client:
            await self.remote_client.destroy_sandbox(handle)
            return

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
        if handle.metadata is not None:
            handle.metadata["destroyed"] = True

    def _terminate_container(self, container_id: str) -> None:
        """Kill and remove a timed-out container as one cleanup operation."""
        container = self.client.containers.get(container_id)
        try:
            container.kill()
        finally:
            container.remove(force=True)

    async def health_check(self) -> BackendHealth:
        if self.remote_client:
            return await self.remote_client.health_check()

        if not self.client:
            return BackendHealth(status="unhealthy", details={"error": "Client not initialized"})

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self.client.ping)
            return BackendHealth(status="healthy", details={"client": "connected"})
        except Exception as e:
            return BackendHealth(status="unhealthy", details={"error": str(e)})
