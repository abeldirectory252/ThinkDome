"""Docker-based Python executor â€” 6-layer security sandbox.

Layer 1: OS-Level Virtualization â€” Ephemeral containers, non-root user (UID 1000:1000)
Layer 2: Filesystem Isolation â€” Read-only rootfs, tmpfs mounts, no host paths
Layer 3: System Call Filtering â€” Custom seccomp profile blocks 30+ dangerous syscalls
Layer 4: Resource Limits (cgroups v2) â€” CPU, memory, PIDs capped by caller role
Layer 5: Capability Dropping â€” cap-drop ALL, no-new-privileges
Layer 6: Network Egress Control â€” Default network=none, optional proxy for ADMIN
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import tarfile
import time
import threading
from pathlib import Path
from pathlib import PurePosixPath
from typing import Optional, AsyncGenerator

import docker
import docker.errors
import requests

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.core.config import Settings
from thinkdome.core.error_codes import SandboxErrorCodes, classify_sandbox_error
from thinkdome.sandbox.executors.host.bubblewrap import _is_env_var_sensitive, _BLOCKED_INTERPRETER_ENV_KEYS
from thinkdome.sandbox.executors.docker.container_policy import DockerContainerPolicy, DockerExecutionPolicy
from thinkdome.sandbox.network.docker_policy import DockerSandboxPolicy

logger = logging.getLogger(__name__)

# ── Resource Limit Profiles ──────────────────────────────────────────────────
# LLM tokens get sandboxed, restricted resources.
# ADMIN tokens can do anything — full resource access.
RESOURCE_PROFILES = {
    "LLM": {
        "cpu_quota":  0.5,          # 0.5 CPU cores
        "memory":     "256m",       # 256 MB RAM
        "memory_swap":"256m",       # No swap (same = swap disabled)
        "pids_limit": 20,           # Prevent fork bombs
        "timeout_max_ms": 10_000,   # 10s max timeout
    },
    "WEB": {
        "cpu_quota":  1.0,          # 1.0 CPU cores
        "memory":     "512m",       # 512 MB RAM
        "memory_swap":"512m",       # No swap
        "pids_limit": 64,           # Normal PID limit
        "timeout_max_ms": 300_000,  # 300s max timeout
    },
    "SDK": {
        "cpu_quota":  1.0,
        "memory":     "512m",
        "memory_swap":"512m",
        "pids_limit": 64,
        "timeout_max_ms": 300_000,
    },
    "CURL": {
        "cpu_quota":  1.0,
        "memory":     "512m",
        "memory_swap":"512m",
        "pids_limit": 64,
        "timeout_max_ms": 300_000,
    },
    "ORCH": {
        "cpu_quota":  2.0,          # 2.0 CPU cores
        "memory":     "1024m",      # 1 GB RAM
        "memory_swap":"1024m",      # No swap
        "pids_limit": 128,          # Generous PID limit
        "timeout_max_ms": 600_000,  # 10 min max timeout
    },
    "IDE": {
        "cpu_quota":  2.0,
        "memory":     "1024m",
        "memory_swap":"1024m",
        "pids_limit": 128,
        "timeout_max_ms": 600_000,
    },
    "ADMIN": {
        "cpu_quota":  2.0,          # 2 CPU cores
        "memory":     "1024m",      # 1 GB RAM
        "memory_swap":"1024m",      # No swap
        "pids_limit": 128,          # Generous PID limit
        "timeout_max_ms": 60_000,   # 60s max timeout
    },
}

from thinkdome.core.config import get_workspace_root

# Seccomp profile path (relative to project root)
SECCOMP_PROFILE_PATH = get_workspace_root() / "security" / "seccomp.json"

def _is_netns_mount_error(error: BaseException) -> bool:
    """Return whether Docker failed before the container could start.

    Docker creates the network namespace and bind-mounts it into its own
    ``/var/run/docker/netns`` directory before it starts the OCI container.
    Consequently this is a Docker-daemon/runtime failure, not an error which
    can be fixed by selecting another network mode for the same sandbox.
    """
    message = str(error).lower()
    return "bind-mount" in message and "/ns/net" in message and "netns" in message


def _network_setup_failure_message(error: BaseException) -> str:
    """Produce an actionable, non-misleading error for Docker netns failures."""
    if _is_netns_mount_error(error):
        return (
            "Container Isolation Error: Docker could not create the sandbox "
            "network namespace. This is a Docker daemon netns mount failure, "
            "before the container or its seccomp profile starts. Check the "
            "dockerd journal and restart Docker to recreate /var/run/docker/netns."
        )
    return "Container Isolation Error: Failed to set up the sandbox network environment."


def _docker_error_code(error: BaseException) -> str:
    """Map Docker API failures to a stable execution error code."""
    if _is_netns_mount_error(error):
        return SandboxErrorCodes.DOCKER_NETNS_SETUP_FAILED
    return SandboxErrorCodes.EXECUTION_FAILED


def _is_wait_timeout(error: BaseException) -> bool:
    """Return whether Docker's wait failure represents the requested timeout.

    Docker SDK timeout failures are transport-specific (typically
    ``ReadTimeout``), while API errors indicate a daemon/runtime failure and
    must propagate to the normal Docker error path instead of being reported
    as a user-code timeout.
    """
    return isinstance(error, (TimeoutError, requests.exceptions.Timeout))


class PythonDockerExecutor(BaseExecutor):
    """Execute Python code in isolated Docker containers with 6-layer security."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.image = settings.EXECUTOR_IMAGE
        self.client: Optional[docker.DockerClient] = None
        self._network_policy: Optional[DockerSandboxPolicy] = None
        self._execution_slots = asyncio.Semaphore(settings.DOCKER_MAX_CONCURRENT_EXECUTIONS)
        self._seccomp_profile: Optional[str] = None
        self.pool_manager = None

    def set_pool_manager(self, pool_manager) -> None:
        """Inject pool manager instance."""
        self.pool_manager = pool_manager

    async def initialize(self) -> None:
        """Connect to Docker daemon, ensure image exists, load seccomp profile."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._init_sync)

    def _init_sync(self) -> None:
        try:
            self.client = docker.from_env()
            self.client.ping()
        except Exception as e:
            if "Permission denied" in str(e) or isinstance(e, PermissionError):
                raise RuntimeError(
                    f"Docker socket permission denied: {e}\n"
                    f"To fix this, choose one of the following:\n"
                    f"  1. Run with sudo: sudo ./venv/bin/python think run '...' --backend docker\n"
                    f"  2. Add user to docker group: sudo usermod -aG docker $USER && newgrp docker\n"
                    f"  3. Use subprocess backend for local dev: ./venv/bin/python think run '...' --backend subprocess"
                ) from e
            raise RuntimeError(f"Could not connect to Docker daemon: {e}") from e

        # Never serve untrusted execution until the configured runtime and
        # production isolation contract have been validated.
        self.settings.validate_production_runtime()
        from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup
        validate_secure_runtime_on_startup(self.settings, docker_client=self.client)

        # Ensure executor image
        try:
            self.client.images.get(self.image)
            logger.info(f"Executor image '{self.image}' found")
        except docker.errors.ImageNotFound:
            logger.warning(f"Image '{self.image}' not found, attempting build...")
            executor_dir = Path(__file__).parent / "executor"

            if executor_dir.exists():
                logger.info(f"Building executor image from {executor_dir}")
                self.client.images.build(
                    path=str(executor_dir),
                    tag=self.image,
                    rm=True,
                )
                logger.info(f"✅ Built executor image '{self.image}'")
            else:
                raise RuntimeError(
                    f"Executor image '{self.image}' not found and cannot build. "
                    f"Run: docker build -t {self.image} docker/executor/"
                )

        # Load seccomp profile (Layer 3)
        if SECCOMP_PROFILE_PATH.exists():
            self._seccomp_profile = SECCOMP_PROFILE_PATH.read_text(encoding="utf-8")
            logger.info(f"✅ Seccomp profile loaded from {SECCOMP_PROFILE_PATH}")
        else:
            logger.warning(f"⚠️  Seccomp profile not found at {SECCOMP_PROFILE_PATH} — using Docker default")

    NETWORK_AUTHORIZED_ROLES = DockerExecutionPolicy.NETWORK_AUTHORIZED_ROLES
    RESOURCE_CUSTOMIZATION_ROLES = DockerExecutionPolicy.RESOURCE_CUSTOMIZATION_ROLES
    # can_customize_resources = role in {"ADMIN", "ORCH", "IDE"}

    def _validate_request(self, request: ExecRequest, role: str) -> None:
        """Validate dataclass input before it can influence Docker config."""
        if not isinstance(request.code, str):
            raise ValueError("Execution code must be a string")
        max_code = int(getattr(self.settings, "MAX_EXECUTION_CODE_BYTES", 1_048_576))
        if len(request.code.encode("utf-8")) > max_code:
            raise ValueError(f"Execution code exceeds the {max_code}-byte limit")
        if type(request.timeout_ms) is not int or request.timeout_ms < 1:
            raise ValueError("Execution timeout must be a positive integer in milliseconds")
        if type(request.max_output_bytes) is not int or request.max_output_bytes < 0:
            raise ValueError("Maximum output size must be a non-negative integer")
        if role not in self.RESOURCE_CUSTOMIZATION_ROLES:
            return
        if request.cpu_cores is not None and (
            isinstance(request.cpu_cores, bool)
            or not isinstance(request.cpu_cores, (int, float))
            or not 0.1 <= float(request.cpu_cores) <= 64
        ):
            raise ValueError("CPU allocation must be between 0.1 and 64 cores")
        if request.memory_limit_mb is not None and (
            type(request.memory_limit_mb) is not int
            or not 16 <= request.memory_limit_mb <= 65_536
        ):
            raise ValueError("Memory allocation must be between 16 and 65536 MiB")

    def _network_config(
        self,
        request: ExecRequest,
        role: str,
        environment: dict[str, str],
    ) -> tuple[str, dict[str, str]]:
        """Resolve network mode and environment through the egress policy."""
        if not request.allow_network:
            logger.info("🔒 Network disabled (profile=%s)", role)
            return "none", environment
        if role not in self.NETWORK_AUTHORIZED_ROLES:
            logger.warning("Network request denied for restricted role '%s'", role)
            return "none", environment
        policy = self._get_network_policy()
        attachment = policy.attachment(True)
        logger.info("🌐 Network access granted for %s token via egress proxy network", role)
        return attachment.mode, policy.enforce_environment(environment, attachment.mode)

    def _get_network_policy(self) -> DockerSandboxPolicy:
        """Return the policy bound to the current Docker client."""
        if not self.client:
            raise RuntimeError("Docker client is required to validate network isolation")
        if self._network_policy is None or self._network_policy.client is not self.client:
            self._network_policy = DockerSandboxPolicy(self.client)
        return self._network_policy

    def _resource_limits(self, request: ExecRequest, profile: dict, role: str) -> dict[str, object]:
        """Resolve bounded cgroup settings for the caller role."""
        customizable = role in self.RESOURCE_CUSTOMIZATION_ROLES
        custom_memory = customizable and request.memory_limit_mb is not None
        memory = f"{request.memory_limit_mb}m" if custom_memory else profile["memory"]
        cpu = request.cpu_cores if customizable and request.cpu_cores is not None else profile["cpu_quota"]
        return {
            "nano_cpus": int(cpu * 1e9),
            "mem_limit": memory,
            "memswap_limit": memory if custom_memory else profile["memory_swap"],
            "pids_limit": profile["pids_limit"],
        }

    @staticmethod
    def _execution_command(request: ExecRequest) -> list[str]:
        """Resolve the interpreter without embedding shell policy in assembly."""
        lang = (request.language or "python").lower()
        is_shell = lang in {"bash", "sh", "shell"} or request.code.strip().startswith("#!")
        return ["/bin/bash", "-c", request.code] if is_shell else ["python3", "-u", "-c", request.code]

    def _build_container_config(self, request: ExecRequest) -> dict:
        """Build the full container creation config with all 6 security layers."""
        role = (request.caller_role or "LLM").upper()
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])
        self._validate_request(request, role)

        # ── Layer 4: Resource Limits (cgroups v2) ──────────────────────────────────
        resource_limits = self._resource_limits(request, profile, role)

        # Enforce timeout ceiling per role
        timeout_max = profile["timeout_max_ms"]
        if request.timeout_ms > timeout_max:
            logger.warning(
                f"Timeout {request.timeout_ms}ms exceeds {role} limit of {timeout_max}ms — capping"
            )

        # ── Layer 6: Network Egress Control ──────────────────────────────────────
        environment = DockerExecutionPolicy.sanitize_environment(request.env_vars)

        network_mode, environment = self._network_config(request, role, environment)

        
        # ── Layer 5: Capability Dropping ──────────────────────────────────────────
        # Egress access does not require privileged port binding. Keep the
        # capability set empty for every network mode.
        cap_drop = ["ALL"]
        cap_add = []

        # ── Layer 3: Seccomp Profile ──────────────────────────────────────────────
        security_opt = ["no-new-privileges:true"]
        if self._seccomp_profile:
            security_opt.append(f"seccomp={self._seccomp_profile}")

        # ── Layer 2: Filesystem Isolation ──────────────────────────────────────────
        # Read-only rootfs + tmpfs for /tmp (64MB, noexec)
        tmpfs_size = DockerContainerPolicy._bounded_size(
            self.settings, "SANDBOX_TMPFS_SIZE_MB", 64, 4096
        )
        tmpfs_config = {
            "/tmp": f"size={tmpfs_size}m,noexec,nosuid,nodev,mode=1777",
        }
        # A caller identity must never select a host bind mount.  In
        # particular, a writable per-user directory on the Docker host would
        # give untrusted code a durable host filesystem capability.  Durable
        # workspaces belong to the volume service and will be attached by the
        # node orchestrator, not by this local Docker compatibility backend.
        tmpfs_config["/workspace"] = f"size={tmpfs_size}m,noexec,nosuid,nodev,mode=1777"
        # Never allow request input to alter executable resolution.
        environment["PATH"] = DockerExecutionPolicy.SAFE_PATH

        # ── Language Command Resolution ────────────────────────────────────────────
        exec_command = self._execution_command(request)

        # ── Layer 1: OS-Level Virtualization ──────────────────────────────────────
        config = {
            "image":        self.image,
            "entrypoint":   "",
            "command":      exec_command,
            "stdin_open":   bool(request.stdin),

            # Layer 1: Ephemeral, non-root user
            "user":         "1000:1000",
            "detach":       True,
            "privileged":   False,
            "init":         True,
            "ipc_mode":     "private",
            "shm_size":     DockerContainerPolicy.shm_size(self.settings),
            "ulimits":      DockerContainerPolicy.nofile_ulimit(self.settings),

            # Layer 2: Filesystem isolation
            "read_only":    True,
            "tmpfs":        tmpfs_config,

            # Layer 4: Resource limits
            **resource_limits,

            # Layer 5: Capability dropping
            "cap_drop":     cap_drop,
            "cap_add":      cap_add if cap_add else None,
            "security_opt": security_opt,

            # Layer 6: Network control
            "network_mode": network_mode,

            # Environment
            "environment":  environment,

            # Working directory
            "working_dir":  "/workspace",
        }

        # Secure OCI runtime (e.g., 'runsc' for gVisor, 'kata-runtime' for Kata)
        runtime = DockerContainerPolicy.runtime(self.settings)
        if runtime:
            config["runtime"] = runtime

        # Remove None values to avoid Docker API errors
        config = {k: v for k, v in config.items() if v is not None}

        return config

    # â”€â”€ Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Run code in an ephemeral Docker container with 6-layer security, using pool if enabled."""
        # Warm containers are permanently attached to network_mode=none. Never
        # reuse one for a network-enabled request: injecting proxy variables
        # cannot add a network namespace and would produce a misleading partial
        # execution path. Cold-start the correctly attached container instead.
        if self.pool_manager and self.settings.POOL_ENABLED and not request.allow_network:
            return await self._execute_pooled(request)
        return await self._execute_cold(request)

    async def _execute_cold(self, request: ExecRequest) -> ExecResult:
        """Run a cold container under the global execution admission limit."""
        loop = asyncio.get_event_loop()
        async with self._execution_slots:
            return await loop.run_in_executor(None, self._execute_sync, request)

    async def _execute_pooled(self, request: ExecRequest) -> ExecResult:
        """Run code in a pre-warmed pooled container.
        # release(pooled.pool_id, reset=False)
        """
        start = time.monotonic()
        role = (request.caller_role or "LLM").upper()
        
        pooled = await self.pool_manager.acquire(role=role)
        if not pooled:
            # Fallback to cold start if pool acquisition failed
            return await self._execute_cold(request)
            
        container_id = pooled.container_id
        container = None
        
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(None, lambda: self.client.containers.get(container_id))
            
            # Inject files into /workspace if requested
            if request.files:
                tar_stream = self._create_tar(request.files)
                await loop.run_in_executor(None, lambda: container.put_archive("/workspace", tar_stream))
                
            # Run code via exec_run / exec_create + exec_start
            cmd = self._execution_command(request)
            exec_env = DockerExecutionPolicy.sanitize_environment(request.env_vars)
            exec_env["PATH"] = DockerExecutionPolicy.SAFE_PATH
            profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])

            def _run_exec_sync():
                exec_id = self.client.api.exec_create(
                    container=container_id,
                    cmd=cmd,
                    user="1000:1000",
                    environment=exec_env,
                )
                output = self.client.api.exec_start(exec_id=exec_id, detach=False)
                inspect = self.client.api.exec_inspect(exec_id=exec_id)
                exit_code = inspect.get("ExitCode", 0)
                return output, exit_code
                
            timeout_sec = min(request.timeout_ms, profile["timeout_max_ms"]) / 1000.0
            try:
                output_bytes, exit_code = await asyncio.wait_for(
                    loop.run_in_executor(None, _run_exec_sync),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                # exec_start is a blocking Docker SDK call. Cancelling the
                # asyncio future does not stop the command, so terminate the
                # pooled container before releasing it and report a real
                # timeout instead of starting an untracked fallback job.
                try:
                    await loop.run_in_executor(None, container.kill)
                except Exception:
                    pass
                await self.pool_manager.release(pooled.pool_id, reset=False, lease_token=pooled.lease_token)
                return ExecResult(
                    stderr="Process timed out.",
                    exit_code=-1,
                    timed_out=True,
                    duration_ms=round((time.monotonic() - start) * 1000, 2),
                )
            
            stdout = output_bytes.decode("utf-8", errors="replace")[: request.max_output_bytes]
            stderr = ""
            
            output_files = {}
            output_files = await loop.run_in_executor(None, self._extract_workspace_files, container, request.files)
                
            duration_ms = (time.monotonic() - start) * 1000
            
            # Release back to pool with reset
            await self.pool_manager.release(pooled.pool_id, reset=True, lease_token=pooled.lease_token)
            
            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
                output_files=output_files,
            )
        except asyncio.CancelledError:
            # Client disconnect/cancellation must not leave a privileged exec
            # running in a pooled container that can later be handed to a
            # different sandbox request.
            try:
                if container is not None:
                    await loop.run_in_executor(None, container.kill)
                    await self.pool_manager.release(pooled.pool_id, reset=False, lease_token=pooled.lease_token)
            except Exception:
                logger.exception("Failed to clean up cancelled pooled execution")
            raise
        except Exception as e:
            logger.error("Pooled execution failed; refusing automatic rerun: %s", type(e).__name__)
            # Release and destroy container since it might be in corrupted state
            try:
                await self.pool_manager.release(pooled.pool_id, reset=False, lease_token=pooled.lease_token)
            except Exception:
                logger.exception("Failed to destroy contaminated pooled container")
            return ExecResult(
                stderr="Sandbox execution failed safely; the execution was not retried.",
                exit_code=-1,
                timed_out=False,
                duration_ms=round((time.monotonic() - start) * 1000, 2),
                error_code=SandboxErrorCodes.EXECUTION_FAILED,
            )

    def _execute_sync(self, request: ExecRequest) -> ExecResult:
        assert self.client is not None

        role = (request.caller_role or "LLM").upper()
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])
        timeout_sec = min(request.timeout_ms, profile["timeout_max_ms"]) / 1000.0
        start = time.monotonic()

        container = None
        try:
            # Build container config with all 6 layers
            config = self._build_container_config(request)

            logger.info(
                f"ðŸ ³ Creating container: role={role}, "
                f"cpu={profile['cpu_quota']}, mem={profile['memory']}, "
                f"pids={profile['pids_limit']}, network={config.get('network_mode', 'none')}"
            )

            container = self.client.containers.create(**config)
            if request.files:
                tar_stream = self._create_tar(request.files)
                container.put_archive("/workspace", tar_stream)
            # Do not fall back to host or bridge networking here.  In
            # particular, an LLM request has deliberately selected "none";
            # changing that after a daemon failure would violate the sandbox
            # network policy and does not repair a missing Docker netns mount.
            container.start()

            # Provide stdin if needed
            if request.stdin:
                sock = container.attach_socket(params={"stdin": 1, "stream": 1})
                sock._sock.sendall(request.stdin.encode("utf-8"))
                sock._sock.close()

            # Wait with timeout
            try:
                result = container.wait(timeout=timeout_sec)
                exit_code = result.get("StatusCode", -1)
                timed_out = False

                # Layer 4: Detect OOM kill
                if exit_code == 137:
                    inspect = container.attrs
                    oom_killed = (
                        inspect.get("State", {}).get("OOMKilled", False)
                    )
                    if oom_killed:
                        logger.warning(f"ðŸ’€ Container OOM-killed (role={role}, limit={profile['memory']})")
                        duration_ms = (time.monotonic() - start) * 1000
                        return ExecResult(
                            stdout="",
                            stderr=f"Process killed: exceeded memory limit ({profile['memory']}). "
                                   f"Your code used more memory than allowed for {role} tokens.",
                            exit_code=137,
                            timed_out=False,
                            duration_ms=round(duration_ms, 2),
                        )

            except Exception as wait_error:
                if not _is_wait_timeout(wait_error):
                    raise
                # Actual wait timeout: terminate the container before
                # collecting output so code cannot continue after the API
                # reports a timeout.
                try:
                    container.kill()
                except Exception:
                    pass
                exit_code = -1
                timed_out = True

            # Collect output
            stdout = self._read_container_logs(container, stdout=True, limit=request.max_output_bytes)
            stderr = self._read_container_logs(container, stderr=True, limit=request.max_output_bytes)

            # /workspace is always an isolated tmpfs. Extract generated files
            # through Docker's archive API rather than exposing a host bind.
            output_files = self._extract_workspace_files(container, request.files)

            duration_ms = (time.monotonic() - start) * 1000

            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=round(duration_ms, 2),
                output_files=output_files,
            )

        except docker.errors.ContainerError as e:
            duration_ms = (time.monotonic() - start) * 1000
            return ExecResult(
                stdout="",
                stderr=str(e),
                exit_code=1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
                error_code=SandboxErrorCodes.EXECUTION_FAILED,
            )
        except docker.errors.APIError as e:
            duration_ms = (time.monotonic() - start) * 1000
            error_code = _docker_error_code(e)
            logger.error("Docker API error [%s]: %s", error_code, e)
            return ExecResult(
                stdout="",
                stderr=_network_setup_failure_message(e),
                exit_code=1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
                error_code=error_code,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"Execution error: {e}", exc_info=True)
            error_code = classify_sandbox_error(e)
            return ExecResult(
                stdout="",
                stderr="Sandbox Execution Error: Unable to launch execution environment.",
                exit_code=-1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
                error_code=error_code,
            )
        finally:
            # Layer 1: Destroy ephemeral container after every execution
            if container:
                try:
                    container.remove(force=True)
                    logger.debug("ðŸ—‘ï¸   Ephemeral container destroyed")
                except Exception:
                    pass

    # â”€â”€ File Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _read_container_logs(container, *, stdout: bool = False, stderr: bool = False, limit: int) -> str:
        """Read container logs with a strict memory bound."""
        remaining = max(0, int(limit))
        chunks: list[bytes] = []
        for chunk in container.logs(stdout=stdout, stderr=stderr, stream=True, follow=False):
            if remaining <= 0:
                break
            data = chunk.encode() if isinstance(chunk, str) else bytes(chunk)
            data = data[:remaining]
            chunks.append(data)
            remaining -= len(data)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _get_user_workspace(self, username: str | None) -> Optional[Path]:
        """Return the persistent workspace directory for a specific user."""
        if not username:
            return None
        project_root = Path(__file__).resolve().parents[4]

        namespace = hashlib.sha256(str(username).encode("utf-8")).hexdigest()[:32]
        workspace = project_root / "storage" / "workspaces" / namespace
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _create_tar(self, files: dict[str, bytes]) -> bytes:
        """Create a tar archive from file dict for container injection."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for path, content in files.items():
                normalized = PurePosixPath(path)
                if (
                    not path
                    or normalized.is_absolute()
                    or any(part in {"", ".", ".."} for part in normalized.parts)
                ):
                    raise ValueError(f"file path escapes workspace: {path!r}")
                info = tarfile.TarInfo(name=path)
                info.size = len(content)
                info.uid = 1000
                info.gid = 1000
                tar.addfile(info, io.BytesIO(content))
        buf.seek(0)
        return buf.read()

    def _extract_workspace_files(
        self, container, input_files: dict[str, bytes]
    ) -> dict[str, bytes]:
        """Extract new/modified files from /workspace."""
        output_files: dict[str, bytes] = {}
        input_names = set(input_files.keys())
        max_total = int(getattr(self.settings, "MAX_OUTPUT_BYTES", 1_048_576))
        total = 0

        try:
            archive_stream, _ = container.get_archive("/workspace")
            buf = io.BytesIO()
            for chunk in archive_stream:
                buf.write(chunk)
            buf.seek(0)

            with tarfile.open(fileobj=buf, mode="r") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    # Strip leading "workspace/" from path
                    name = member.name
                    if name.startswith("workspace/"):
                        name = name[len("workspace/"):]
                    path = PurePosixPath(name)
                    if (not name or name in input_names or path.is_absolute()
                            or any(part in {"", ".", ".."} for part in path.parts)):
                        continue
                    if total >= max_total:
                        break
                    f = tar.extractfile(member)
                    if f:
                        content = f.read(max_total - total)
                        output_files[name] = content
                        total += len(content)
        except Exception as e:
            logger.debug(f"Could not extract workspace files: {e}")

        return output_files

    # â”€â”€ Lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def shutdown(self) -> None:
        """Close Docker client."""
        if self.client:
            self.client.close()

    async def health_check(self) -> bool:
        """Check Docker daemon connectivity."""
        if not self.client:
            return False
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Run code in an ephemeral Docker container and stream output in real-time."""
        assert self.client is not None

        role = (request.caller_role or "LLM").upper()
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])
        timeout_sec = min(request.timeout_ms, profile["timeout_max_ms"]) / 1000.0
        start = time.monotonic()

        container = None
        slot_acquired = False
        bg_task = None
        try:
            await self._execution_slots.acquire()
            slot_acquired = True
            config = self._build_container_config(request)
            
            loop = asyncio.get_running_loop()

            def _create_container():
                """Create a stopped container without weakening its policy."""
                return self.client.containers.create(**config)

            container = await loop.run_in_executor(None, _create_container)

            if request.files:
                tar_stream = self._create_tar(request.files)
                await loop.run_in_executor(
                    None,
                    lambda: container.put_archive("/workspace", tar_stream)
                )

            # Uploads must be complete before user code can run. Starting
            # first creates a TOCTOU race where code observes partial or
            # missing inputs and may finish before the archive is installed.
            await loop.run_in_executor(None, container.start)

            if request.stdin:
                def send_stdin():
                    sock = container.attach_socket(params={"stdin": 1, "stream": 1})
                    sock._sock.sendall(request.stdin.encode("utf-8"))
                    sock._sock.close()
                await loop.run_in_executor(None, send_stdin)

            queue = asyncio.Queue()
            output_limit = max(0, int(request.max_output_bytes))
            output_bytes = 0
            output_lock = threading.Lock()
            _DONE = object()

            def collect_logs():
                nonlocal output_bytes
                try:
                    log_generator = container.logs(
                        stdout=True,
                        stderr=True,
                        stream=True,
                        follow=True,
                        demux=True,
                    )
                    for chunk in log_generator:
                        # Docker returns (stdout, stderr) when demux=True.
                        # Keep channels distinct so stderr cannot be mistaken
                        # for successful program output.
                        records = chunk if isinstance(chunk, tuple) else (chunk, None)
                        for channel, payload in zip(("stdout", "stderr"), records):
                            if not payload:
                                continue
                            with output_lock:
                                remaining = output_limit - output_bytes
                                if remaining <= 0:
                                    continue
                                payload = payload[:remaining]
                                output_bytes += len(payload)
                            text = payload.decode("utf-8", errors="replace")
                            loop.call_soon_threadsafe(queue.put_nowait, (channel, text))
                except Exception as e:
                    logger.debug(f"Logs streaming ended/interrupted: {e}")

            collector_future = loop.run_in_executor(None, collect_logs)

            async def wait_container():
                return await loop.run_in_executor(None, lambda: container.wait(timeout=timeout_sec))

            async def _run_all():
                try:
                    await wait_container()
                except Exception as wait_error:
                    if not _is_wait_timeout(wait_error):
                        raise
                    try:
                        await loop.run_in_executor(None, container.kill)
                    except Exception:
                        pass
                    await queue.put(("stderr", "\nProcess timed out.\n"))
                
                # Wait for logs to be fully collected
                try:
                    await collector_future
                except Exception:
                    pass
                await queue.put(_DONE)

            bg_task = asyncio.create_task(_run_all())

            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield item

            await bg_task

        except docker.errors.APIError as e:
            error_code = _docker_error_code(e)
            message = _network_setup_failure_message(e)
            logger.error("Streaming Docker API error [%s]: %s", error_code, e, exc_info=True)
            yield "error", json.dumps({"code": error_code, "message": message})
            yield "stderr", message
        except Exception as e:
            logger.error(f"Streaming execution error: {e}", exc_info=True)
            yield "stderr", "Sandbox Execution Error: Unable to launch execution environment."
        finally:
            if slot_acquired:
                self._execution_slots.release()
            if bg_task:
                bg_task.cancel()
            if container:
                try:
                    await loop.run_in_executor(None, lambda: container.remove(force=True))
                    logger.debug("🗑️ Ephemeral container destroyed")
                except Exception:
                    pass
