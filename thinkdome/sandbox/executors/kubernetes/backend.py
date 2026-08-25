"""Kubernetes pod executor backend implementation for ThinkDome.

Executes code sandboxes in dedicated gVisor-isolated pods via the Kubernetes API.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from typing import Any, Dict, Optional

from kubernetes import client, config, watch
from kubernetes.stream import stream

from thinkdome.sandbox.executors.executor_backend import (
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
        self._networking_client: Optional[client.NetworkingV1Api] = None
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
            self._networking_client = client.NetworkingV1Api()
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

        sandbox_hash = hashlib.sha256(sandbox_id.encode()).hexdigest()[:32]
        pod_name = f"thinkdome-sb-{sandbox_hash}"
        namespace = self.settings.K8S_NAMESPACE
        # Use a deterministic, DNS-safe name independent of user-controlled IDs.
        policy_name = f"thinkdome-deny-egress-{sandbox_hash[:16]}"

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
                    "sandbox_hash": sandbox_hash,
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

        # A disabled network must be enforced by the cluster, not merely recorded
        # in control-plane state.  Create a pod-scoped deny-all egress policy
        # immediately after pod creation; if policy setup fails, remove the pod so
        # a sandbox is never exposed with an unintended network configuration.
        if not network_enabled:
            if self._networking_client is None:
                await self.destroy_sandbox(
                    SandboxHandle(sandbox_id=sandbox_id, container_id=pod_name, backend_type="kubernetes")
                )
                raise RuntimeError("Kubernetes networking client is unavailable; refusing network-disabled sandbox")
            policy = client.V1NetworkPolicy(
                metadata=client.V1ObjectMeta(name=policy_name),
                spec=client.V1NetworkPolicySpec(
                    pod_selector=client.V1LabelSelector(match_labels={"sandbox_hash": sandbox_hash}),
                    policy_types=["Egress"],
                    egress=[],
                ),
            )
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._networking_client.create_namespaced_network_policy(
                        namespace=namespace,
                        body=policy,
                    ),
                )
            except Exception:
                await self.destroy_sandbox(
                    SandboxHandle(sandbox_id=sandbox_id, container_id=pod_name, backend_type="kubernetes")
                )
                raise RuntimeError("Failed to install network isolation policy")

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
        # Match the non-root UID baked into the executor image.
        user: str = "1000",
        env_vars: Optional[Dict[str, str]] = None,
        timeout_ms: int = 10000,
    ) -> ExecutionResult:
        self._init_client()
        if not self._initialized or not self._v1_client:
            raise RuntimeError("Kubernetes client is not initialized")

        pod_name = handle.container_id
        namespace = self.settings.K8S_NAMESPACE
        policy_name = f"thinkdome-deny-egress-{hashlib.sha256(handle.sandbox_id.encode()).hexdigest()[:16]}"
        loop = asyncio.get_event_loop()
        start = time.perf_counter()

        # Build env wrapper command if env_vars exist
        exec_cmd = command
        if env_vars:
            invalid_env = [k for k in env_vars if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)]
            if invalid_env:
                raise ValueError(f"Invalid environment variable names: {invalid_env}")
            env_prefixes = [f"{k}={v}" for k, v in env_vars.items()]
            exec_cmd = ["env"] + env_prefixes + command

        response_holder: Dict[str, Any] = {}
        cancelled = threading.Event()

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
            response_holder["resp"] = resp
            if cancelled.is_set():
                resp.close()
                return "", "Kubernetes exec command timed out.", -1
            try:
                # Read output blocking
                resp.run_forever(timeout=timeout_ms / 1000.0)
                stdout = resp.read_stdout() or ""
                stderr = resp.read_stderr() or ""
                exit_code = resp.returncode or 0
                return stdout, stderr, exit_code
            finally:
                try:
                    resp.close()
                except Exception:
                    logger.debug("Unable to close Kubernetes exec stream", exc_info=True)

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
            cancelled.set()
            resp = response_holder.get("resp")
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    logger.debug("Unable to cancel Kubernetes exec stream", exc_info=True)
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

        if self._networking_client is not None:
            def _delete_policy():
                try:
                    self._networking_client.delete_namespaced_network_policy(
                        name=policy_name,
                        namespace=namespace,
                        body=client.V1DeleteOptions(),
                    )
                except Exception:
                    # A stale deny policy is fail-closed and can be reaped later.
                    logger.debug("Unable to delete network policy %s", policy_name, exc_info=True)

            await loop.run_in_executor(None, _delete_policy)

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
