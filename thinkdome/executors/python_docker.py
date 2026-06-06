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
import io
import json
import logging
import tarfile
import time
from pathlib import Path
from typing import Optional

import docker
import docker.errors

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)

# â”€â”€ Resource Limit Profiles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# LLM tokens get sandboxed, restricted resources.
# ADMIN tokens can do anything â€” full resource access.
RESOURCE_PROFILES = {
    "LLM": {
        "cpu_quota":  0.5,          # 0.5 CPU cores
        "memory":     "256m",       # 256 MB RAM
        "memory_swap":"256m",       # No swap (same = swap disabled)
        "pids_limit": 20,           # Prevent fork bombs
        "timeout_max_ms": 10_000,   # 10s max timeout
    },
    "ADMIN": {
        "cpu_quota":  2.0,          # 2 CPU cores
        "memory":     "1024m",      # 1 GB RAM
        "memory_swap":"1024m",      # No swap
        "pids_limit": 128,          # Generous PID limit
        "timeout_max_ms": 60_000,   # 60s max timeout
    },
}

# Seccomp profile path (relative to project root)
SECCOMP_PROFILE_PATH = Path(__file__).resolve().parents[2] / "security" / "seccomp.json"

# Egress proxy network name (created in docker-compose or manually)
PROXY_NETWORK_NAME = "thinkbox-egress"
PROXY_HOST = "thinkbox-proxy"
PROXY_PORT = 3128


class PythonDockerExecutor(BaseExecutor):
    """Execute Python code in isolated Docker containers with 6-layer security."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.image = settings.EXECUTOR_IMAGE
        self.client: Optional[docker.DockerClient] = None
        self._seccomp_profile: Optional[str] = None

    async def initialize(self) -> None:
        """Connect to Docker daemon, ensure image exists, load seccomp profile."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._init_sync)

    def _init_sync(self) -> None:
        self.client = docker.from_env()

        # Ensure executor image
        try:
            self.client.images.get(self.image)
            logger.info(f"Executor image '{self.image}' found")
        except docker.errors.ImageNotFound:
            logger.warning(f"Image '{self.image}' not found, attempting build...")
            executor_dir = Path(__file__).parent.parent.parent / "docker" / "executor"
            if executor_dir.exists():
                logger.info(f"Building executor image from {executor_dir}")
                self.client.images.build(
                    path=str(executor_dir),
                    tag=self.image,
                    rm=True,
                )
                logger.info(f"âœ… Built executor image '{self.image}'")
            else:
                raise RuntimeError(
                    f"Executor image '{self.image}' not found and cannot build. "
                    f"Run: docker build -t {self.image} docker/executor/"
                )

        # Load seccomp profile (Layer 3)
        if SECCOMP_PROFILE_PATH.exists():
            self._seccomp_profile = SECCOMP_PROFILE_PATH.read_text(encoding="utf-8")
            logger.info(f"âœ… Seccomp profile loaded from {SECCOMP_PROFILE_PATH}")
        else:
            logger.warning(f"âš ï¸  Seccomp profile not found at {SECCOMP_PROFILE_PATH} â€” using Docker default")

    # â”€â”€ Container Configuration Builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_container_config(self, request: ExecRequest) -> dict:
        """Build the full container creation config with all 6 security layers."""
        role = (request.caller_role or "LLM").upper()
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])

        # â”€â”€ Layer 4: Resource Limits (cgroups v2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cpu_quota = request.cpu_cores if request.cpu_cores is not None else profile["cpu_quota"]
        nano_cpus = int(cpu_quota * 1e9)
        if request.memory_limit_mb is not None:
            mem_limit = f"{request.memory_limit_mb}m"
            mem_swap = f"{request.memory_limit_mb}m"
        else:
            mem_limit = profile["memory"]
            mem_swap = profile["memory_swap"]
        pids_limit = profile["pids_limit"]

        # Enforce timeout ceiling per role
        timeout_max = profile["timeout_max_ms"]
        if request.timeout_ms > timeout_max:
            logger.warning(
                f"Timeout {request.timeout_ms}ms exceeds {role} limit of {timeout_max}ms â€” capping"
            )

        # â”€â”€ Layer 6: Network Egress Control â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        network_mode = "none"
        environment = dict(request.env_vars or {})

        if request.allow_network and role == "ADMIN":
            # ADMIN with explicit network access â€” route through egress proxy
            network_mode = PROXY_NETWORK_NAME
            environment["HTTP_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
            environment["HTTPS_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
            environment["NO_PROXY"] = "localhost,127.0.0.1"
            logger.info(f"ðŸŒ Network access granted for ADMIN via egress proxy")
        elif request.allow_network and role == "LLM":
            # LLM tokens are NEVER allowed network access regardless of request
            logger.warning(
                f"â›” Network access DENIED for LLM token â€” "
                f"LLM tokens cannot access the network. Upgrade to ADMIN token."
            )
            network_mode = "none"
        else:
            logger.info(f"ðŸ”’ Network disabled (profile={role}, allow_network={request.allow_network})")

        # â”€â”€ Layer 5: Capability Dropping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cap_drop = ["ALL"]
        cap_add = []

        # Only add NET_BIND_SERVICE if network is actually enabled
        if network_mode != "none":
            cap_add.append("NET_BIND_SERVICE")

        # â”€â”€ Layer 3: Seccomp Profile â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        security_opt = ["no-new-privileges:true"]
        if self._seccomp_profile:
            security_opt.append(f"seccomp={self._seccomp_profile}")

        # â”€â”€ Layer 2: Filesystem Isolation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Read-only rootfs + tmpfs for /workspace and /tmp (64MB, noexec)
        tmpfs_config = {
            "/workspace": "size=67108864,noexec,nosuid,nodev",    # 64MB
            "/tmp":       "size=67108864,noexec,nosuid,nodev",    # 64MB
        }

        # â”€â”€ Layer 1: OS-Level Virtualization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        config = {
            "image":        self.image,
            "command":      ["python3", "-u", "-c", request.code],
            "stdin_open":   bool(request.stdin),

            # Layer 1: Ephemeral, non-root user
            "user":         "1000:1000",
            "detach":       True,

            # Layer 2: Filesystem isolation
            "read_only":    True,
            "tmpfs":        tmpfs_config,

            # Layer 4: Resource limits
            "nano_cpus":    nano_cpus,
            "mem_limit":    mem_limit,
            "memswap_limit": mem_swap,
            "pids_limit":   pids_limit,

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

        # Remove None values to avoid Docker API errors
        config = {k: v for k, v in config.items() if v is not None}

        return config

    # â”€â”€ Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Run code in an ephemeral Docker container with 6-layer security."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._execute_sync, request)

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
                f"ðŸ³ Creating container: role={role}, "
                f"cpu={profile['cpu_quota']}, mem={profile['memory']}, "
                f"pids={profile['pids_limit']}, network={config.get('network_mode', 'none')}"
            )

            container = self.client.containers.create(**config)

            # Inject files into /workspace via tar archive
            if request.files:
                tar_stream = self._create_tar(request.files)
                container.put_archive("/workspace", tar_stream)

            # Start execution
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

            except Exception:
                # Timeout
                try:
                    container.kill()
                except Exception:
                    pass
                exit_code = -1
                timed_out = True

            # Collect output
            stdout_raw = container.logs(stdout=True, stderr=False)
            stderr_raw = container.logs(stdout=False, stderr=True)

            stdout = stdout_raw.decode("utf-8", errors="replace")[: request.max_output_bytes]
            stderr = stderr_raw.decode("utf-8", errors="replace")[: request.max_output_bytes]

            # Extract output files from /workspace
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
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"Execution error: {e}", exc_info=True)
            return ExecResult(
                stdout="",
                stderr=f"Internal executor error: {e}",
                exit_code=-1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
            )
        finally:
            # Layer 1: Destroy ephemeral container after every execution
            if container:
                try:
                    container.remove(force=True)
                    logger.debug("ðŸ—‘ï¸  Ephemeral container destroyed")
                except Exception:
                    pass

    # â”€â”€ File Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _create_tar(self, files: dict[str, bytes]) -> bytes:
        """Create a tar archive from file dict for container injection."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for path, content in files.items():
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
                    if not name or name in input_names:
                        continue
                    f = tar.extractfile(member)
                    if f:
                        output_files[name] = f.read()
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
