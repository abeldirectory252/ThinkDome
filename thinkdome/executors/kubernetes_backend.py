"""Kubernetes pod executor backend implementation for ThinkDome.

Executes code sandboxes in dedicated gVisor-isolated pods via the Kubernetes API.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from kubernetes import client, config, watch
from kubernetes.stream import stream

from thinkdome.executors.executor_backend import (
    BackendHealth,
    ExecutionResult,
    ExecutorBackend,
    SandboxHandle,
)
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)


class KubernetesBackend(ExecutorBackend):
    """Kubernetes pod execution sandbox backend."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._v1_client: Optional[client.CoreV1Api] = None
        self._initialized = False

    def _init_client(self) -> None:
        """Lazy initialization of K8s client to support local testing without active K8s context."""
        if self._initialized:
            return

        try:
            if self.settings.K8S_IN_CLUSTER:
                config.load_incluster_config()
            else:
                config.load_kube_config()
            self._v1_client = client.CoreV1Api()
            self._initialized = True
            logger.info("☸️ Kubernetes API client initialized")
        except Exception as e:
            logger.warning(f"☸️ Failed to initialize Kubernetes client: {e}")
            self._initialized = False

    async def create_sandbox(
        self,
        sandbox_id: str,
        memory_mb: int,
        cpu_cores: float,
        network_enabled: bool,
        gpu_count: int = 0,
    ) -> SandboxHandle:
        self._init_client()
        if not self._initialized or not self._v1_client:
            raise RuntimeError("Kubernetes client is not initialized")

        pod_name = f"thinkdome-sb-{sandbox_id}"
        namespace = self.settings.K8S_NAMESPACE

        # Define pod specs
        container_resources = {
            "requests": {
                "cpu": f"{int(cpu_cores * 1000)}m",
                "memory": f"{memory_mb}Mi",
            },
            "limits": {
                "cpu": f"{int(cpu_cores * 1000)}m",
                "memory": f"{memory_mb}Mi",
            },
        }

        if gpu_count > 0:
            container_resources["limits"][self.settings.GPU_DEVICE_TYPE] = str(gpu_count)

        # Build Pod spec
        pod_manifest = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "role": "sandbox",
                    "sandbox_id": sandbox_id,
                },
            ),
            spec=client.V1PodSpec(
                runtime_class_name=self.settings.K8S_RUNTIME_CLASS,
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="executor",
                        image=self.settings.EXECUTOR_IMAGE,
                        command=["sleep", "infinity"],
                        resources=client.V1ResourceRequirements(
                            requests=container_resources["requests"],
                            limits=container_resources["limits"],
                        ),
                        security_context=client.V1SecurityContext(
                            allow_privilege_escalation=False,
                            capabilities=client.V1Capabilities(drop=["ALL"]),
                            read_only_root_filesystem=True,
                            run_as_non_root=True,
                            run_as_user=1000,
                            run_as_group=1000,
                            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="tmp-vol",
                                mount_path="/tmp",
                            ),
                            client.V1VolumeMount(
                                name="workspace-vol",
                                mount_path="/workspace",
                            ),
                        ],
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="tmp-vol",
                        empty_dir=client.V1EmptyDirVolumeSource(medium="Memory", size_limit="64Mi"),
                    ),
                    client.V1Volume(
                        name="workspace-vol",
                        empty_dir=client.V1EmptyDirVolumeSource(medium="Memory", size_limit="64Mi"),
                    ),
                ],
            ),
        )

        loop = asyncio.get_event_loop()

        # Create the pod
        await loop.run_in_executor(
            None,
            lambda: self._v1_client.create_namespaced_pod(
                namespace=namespace,
                body=pod_manifest,
            ),
        )

        # Wait for Pod to become Running
        start_time = time.monotonic()
        while time.monotonic() - start_time < 30.0:
            pod_status = await loop.run_in_executor(
                None,
                lambda: self._v1_client.read_namespaced_pod_status(
                    name=pod_name,
                    namespace=namespace,
                ),
            )
            if pod_status.status.phase == "Running":
                pod_ip = pod_status.status.pod_ip
                return SandboxHandle(
                    sandbox_id=sandbox_id,
                    container_id=pod_name,
                    backend_type="kubernetes",
                    ip_address=pod_ip,
                )
            await asyncio.sleep(0.5)

        raise TimeoutError(f"Pod {pod_name} failed to reach Running phase in 30 seconds")

    async def execute_in_sandbox(
        self,
        handle: SandboxHandle,
        command: list[str],
        user: str = "sandboxuser",
        env_vars: Optional[Dict[str, str]] = None,
        timeout_ms: int = 10000,
    ) -> ExecutionResult:
        self._init_client()
        if not self._initialized or not self._v1_client:
            raise RuntimeError("Kubernetes client is not initialized")

        pod_name = handle.container_id
        namespace = self.settings.K8S_NAMESPACE
        loop = asyncio.get_event_loop()
        start = time.perf_counter()

        # Build env wrapper command if env_vars exist
        exec_cmd = command
        if env_vars:
            env_prefixes = [f"{k}={v}" for k, v in env_vars.items()]
            exec_cmd = ["env"] + env_prefixes + command

        def _exec():
            # stream connects and returns stdout/stderr combined or distinct
            resp = stream(
                self._v1_client.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=namespace,
                command=exec_cmd,
                container="executor",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            # Read output blocking
            resp.run_forever(timeout=timeout_ms / 1000.0)
            stdout = resp.read_stdout() or ""
            stderr = resp.read_stderr() or ""
            exit_code = resp.returncode or 0
            return stdout, stderr, exit_code

        try:
            stdout, stderr, exit_code = await asyncio.wait_for(
                loop.run_in_executor(None, _exec),
                timeout=(timeout_ms + 500) / 1000.0,
            )
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=False,
                duration_ms=duration_ms,
            )
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                stdout="",
                stderr="Kubernetes exec command timed out.",
                exit_code=-1,
                timed_out=True,
                duration_ms=duration_ms,
            )

    async def destroy_sandbox(self, handle: SandboxHandle) -> None:
        self._init_client()
        if not self._initialized or not self._v1_client:
            return

        pod_name = handle.container_id
        namespace = self.settings.K8S_NAMESPACE
        loop = asyncio.get_event_loop()

        def _delete():
            try:
                self._v1_client.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace,
                    body=client.V1DeleteOptions(grace_period_seconds=0),
                )
            except Exception:
                pass

        await loop.run_in_executor(None, _delete)

    async def health_check(self) -> BackendHealth:
        self._init_client()
        if not self._initialized or not self._v1_client:
            return BackendHealth(
                status="unhealthy",
                details={"error": "Kubernetes API client not initialized"},
            )

        loop = asyncio.get_event_loop()
        try:
            # Simple list namespace check to verify authentication and connectivity
            await loop.run_in_executor(
                None,
                lambda: self._v1_client.list_namespaced_pod(
                    namespace=self.settings.K8S_NAMESPACE,
                    limit=1,
                ),
            )
            return BackendHealth(status="healthy", details={"api": "connected"})
        except Exception as e:
            return BackendHealth(status="unhealthy", details={"error": str(e)})
