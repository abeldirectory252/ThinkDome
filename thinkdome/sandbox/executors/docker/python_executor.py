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
from typing import Optional, AsyncGenerator

import docker
import docker.errors

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.core.config import Settings

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
        self.pool_manager = None

    def set_pool_manager(self, pool_manager) -> None:
        """Inject pool manager instance."""
        self.pool_manager = pool_manager

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

    def _has_network(self, network_name: str) -> bool:
        """Check if a specific Docker network exists on the daemon."""
        if not self.client:
            return False
        try:
            networks = self.client.networks.list(names=[network_name])
            return len(networks) > 0
        except Exception:
            return False

    def _build_container_config(self, request: ExecRequest) -> dict:
        """Build the full container creation config with all 6 security layers."""
        role = (request.caller_role or "LLM").upper()
        if role == "LLM" and request.allow_network and request.username:
            role = "IDE"
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])

        # ── Layer 4: Resource Limits (cgroups v2) ──────────────────────────────────
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
                f"Timeout {request.timeout_ms}ms exceeds {role} limit of {timeout_max}ms — capping"
            )

        # ── Layer 6: Network Egress Control ──────────────────────────────────────
        network_mode = "none"
        environment = dict(request.env_vars or {})

        if request.allow_network and role in ("ADMIN", "ORCH", "IDE", "WEB", "SDK", "CURL"):
            # Network access allowed for authenticated roles — route through egress proxy network
            network_mode = PROXY_NETWORK_NAME
            environment["HTTP_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
            environment["HTTPS_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
            environment["NO_PROXY"] = "localhost,127.0.0.1"
            logger.info(f"🌐 Network access granted for {role} token via egress proxy network")
        elif request.allow_network and role == "LLM":
            # Restricted untrusted LLM tokens are NEVER allowed network access regardless of request
            logger.warning(
                f"🚫 Network access DENIED for {role} token — "
                f"{role} tokens cannot access the network. Upgrade to ORCH/IDE/ADMIN token."
            )
            network_mode = "none"
        else:
            logger.info(f"🔒 Network disabled (profile={role}, allow_network={request.allow_network})")

        
        # ── Layer 5: Capability Dropping ──────────────────────────────────────────
        cap_drop = ["ALL"]
        cap_add = []

        # Only add NET_BIND_SERVICE if network is actually enabled
        if network_mode != "none":
            cap_add.append("NET_BIND_SERVICE")

        # ── Layer 3: Seccomp Profile ──────────────────────────────────────────────
        security_opt = ["no-new-privileges:true"]
        if self._seccomp_profile:
            security_opt.append(f"seccomp={self._seccomp_profile}")

        # ── Layer 2: Filesystem Isolation ──────────────────────────────────────────
        # Read-only rootfs + tmpfs for /tmp (64MB, noexec)
        tmpfs_config = {
            "/tmp":       "size=67108864,noexec,nosuid,nodev",    # 64MB
        }
        volumes = None

        user_workspace = self._get_user_workspace(request.username)
        if user_workspace:
            volumes = {
                str(user_workspace.resolve()): {
                    "bind": "/workspace",
                    "mode": "rw"
                }
            }
            # Inject environment variables for persistent pip packages
            environment["PYTHONUSERBASE"] = "/workspace/.pip"
            environment["PIP_USER"] = "true"
            # Prepend the site-packages bin, sbin paths and PYTHONPATH
            existing_path = environment.get("PATH", "/sbin:/usr/sbin:/usr/local/sbin:/usr/local/bin:/usr/bin:/bin")
            environment["PATH"] = f"/workspace/.pip/bin:{existing_path}"
            
            existing_pypath = environment.get("PYTHONPATH", "")
            site_packages = "/workspace/.pip/lib/python3.9/site-packages"
            environment["PYTHONPATH"] = f"{site_packages}:{existing_pypath}" if existing_pypath else site_packages
        else:
            tmpfs_config["/workspace"] = "size=67108864,noexec,nosuid,nodev"
            if "PATH" not in environment:
                environment["PATH"] = "/sbin:/usr/sbin:/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"

        # ── Language Command Resolution ────────────────────────────────────────────
        lang = (request.language or "python").lower()
        if lang in ("bash", "sh", "shell") or request.code.strip().startswith("#!"):
            exec_command = ["/bin/bash", "-c", request.code]
        else:
            exec_command = ["python3", "-u", "-c", request.code]

        # ── Layer 1: OS-Level Virtualization ──────────────────────────────────────
        config = {
            "image":        self.image,
            "entrypoint":   "",
            "command":      exec_command,
            "stdin_open":   bool(request.stdin),

            # Layer 1: Ephemeral, non-root user
            "user":         "1000:1000",
            "detach":       True,

            # Layer 2: Filesystem isolation
            "read_only":    True,
            "tmpfs":        tmpfs_config,
            "volumes":      volumes,

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

        # Secure OCI runtime (e.g., 'runsc' for gVisor, 'kata-runtime' for Kata)
        if getattr(self.settings, "SECURE_RUNTIME_TYPE", ""):
            config["runtime"] = getattr(self.settings, "DOCKER_RUNTIME", "runsc")

        # Remove None values to avoid Docker API errors
        config = {k: v for k, v in config.items() if v is not None}

        return config

    # â”€â”€ Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Run code in an ephemeral Docker container with 6-layer security, using pool if enabled."""
        if self.pool_manager and self.settings.POOL_ENABLED:
            return await self._execute_pooled(request)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._execute_sync, request)

    async def _execute_pooled(self, request: ExecRequest) -> ExecResult:
        """Run code in a pre-warmed pooled container."""
        start = time.monotonic()
        role = (request.caller_role or "LLM").upper()
        
        pooled = await self.pool_manager.acquire(role=role)
        if not pooled:
            # Fallback to cold start if pool acquisition failed
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._execute_sync, request)
            
        container_id = pooled.container_id
        
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(None, lambda: self.client.containers.get(container_id))
            
            # Inject files into /workspace if requested
            if request.files:
                tar_stream = self._create_tar(request.files)
                await loop.run_in_executor(None, lambda: container.put_archive("/workspace", tar_stream))
                
            # Run code via exec_run / exec_create + exec_start
            cmd = ["python3", "-u", "-c", request.code]
            exec_env = dict(request.env_vars or {})
            profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])
            
            # Proxy config for network allowance
            if request.allow_network and role in ("ADMIN", "ORCH", "IDE"):
                exec_env["HTTP_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
                exec_env["HTTPS_PROXY"] = f"http://{PROXY_HOST}:{PROXY_PORT}"
                exec_env["NO_PROXY"] = "localhost,127.0.0.1"

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
                
            output_bytes, exit_code = await loop.run_in_executor(None, _run_exec_sync)
            
            stdout = output_bytes.decode("utf-8", errors="replace")[: request.max_output_bytes]
            stderr = ""
            
            output_files = {}
            if not request.username:
                output_files = await loop.run_in_executor(None, self._extract_workspace_files, container, request.files)
                
            duration_ms = (time.monotonic() - start) * 1000
            
            # Release back to pool with reset
            await self.pool_manager.release(pooled.pool_id, reset=True)
            
            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
                output_files=output_files,
            )
        except Exception as e:
            logger.error(f"Pooled execution failed, falling back to cold container: {e}")
            # Release and destroy container since it might be in corrupted state
            await self.pool_manager.release(pooled.pool_id, reset=False)
            
            # Fallback to cold start
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
                f"ðŸ ³ Creating container: role={role}, "
                f"cpu={profile['cpu_quota']}, mem={profile['memory']}, "
                f"pids={profile['pids_limit']}, network={config.get('network_mode', 'none')}"
            )

            try:
                container = self.client.containers.create(**config)
                if request.files:
                    tar_stream = self._create_tar(request.files)
                    container.put_archive("/workspace", tar_stream)
                container.start()
            except docker.errors.APIError as net_err:
                err_msg = str(net_err).lower()
                if "network" in err_msg and ("not found" in err_msg or "failed to set up" in err_msg or "404" in err_msg):
                    logger.warning(
                        f"Egress network '{config.get('network_mode')}' failed on Docker host — recreating container with 'bridge' network mode"
                    )
                    try:
                        if container:
                            container.remove(force=True)
                    except Exception:
                        pass
                    config["network_mode"] = "bridge"
                    container = self.client.containers.create(**config)
                    if request.files:
                        tar_stream = self._create_tar(request.files)
                        container.put_archive("/workspace", tar_stream)
                    container.start()
                else:
                    raise

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

            # Extract output files from /workspace (skip if using persistent host volume)
            if request.username:
                output_files = {}
            else:
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
        except docker.errors.APIError as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"Docker API error: {e}", exc_info=True)
            return ExecResult(
                stdout="",
                stderr="Container Isolation Error: Failed to setup sandbox network environment.",
                exit_code=1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"Execution error: {e}", exc_info=True)
            return ExecResult(
                stdout="",
                stderr="Sandbox Execution Error: Unable to launch execution environment.",
                exit_code=-1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
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

    def _get_user_workspace(self, username: str | None) -> Optional[Path]:
        """Return the persistent workspace directory for a specific user."""
        if not username:
            return None
        project_root = Path(__file__).resolve().parents[4]

        workspace = project_root / "storage" / "workspaces" / username
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

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

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Run code in an ephemeral Docker container and stream output in real-time."""
        assert self.client is not None

        role = (request.caller_role or "LLM").upper()
        profile = RESOURCE_PROFILES.get(role, RESOURCE_PROFILES["LLM"])
        timeout_sec = min(request.timeout_ms, profile["timeout_max_ms"]) / 1000.0
        start = time.monotonic()

        container = None
        bg_task = None
        try:
            config = self._build_container_config(request)
            
            loop = asyncio.get_running_loop()

            def _create_and_start():
                """Create and start container with automatic network fallback."""
                try:
                    c = self.client.containers.create(**config)
                except docker.errors.APIError as net_err:
                    if "network" in str(net_err).lower() and "not found" in str(net_err).lower():
                        logger.warning(
                            f"Egress network '{config.get('network_mode')}' not found — falling back to 'bridge'"
                        )
                        config["network_mode"] = "bridge"
                        c = self.client.containers.create(**config)
                    else:
                        raise
                try:
                    c.start()
                except docker.errors.APIError as start_err:
                    if "network" in str(start_err).lower() and "not found" in str(start_err).lower():
                        logger.warning(
                            f"Network start failed — recreating container with 'bridge' network mode"
                        )
                        try:
                            c.remove(force=True)
                        except Exception:
                            pass
                        config["network_mode"] = "bridge"
                        c = self.client.containers.create(**config)
                        c.start()
                    else:
                        raise
                return c

            container = await loop.run_in_executor(None, _create_and_start)

            if request.files:
                tar_stream = self._create_tar(request.files)
                await loop.run_in_executor(
                    None,
                    lambda: container.put_archive("/workspace", tar_stream)
                )

            if request.stdin:
                def send_stdin():
                    sock = container.attach_socket(params={"stdin": 1, "stream": 1})
                    sock._sock.sendall(request.stdin.encode("utf-8"))
                    sock._sock.close()
                await loop.run_in_executor(None, send_stdin)

            queue = asyncio.Queue()
            _DONE = object()

            def collect_logs():
                try:
                    log_generator = container.logs(
                        stdout=True,
                        stderr=True,
                        stream=True,
                        follow=True
                    )
                    for chunk in log_generator:
                        text = chunk.decode("utf-8", errors="replace")
                        loop.call_soon_threadsafe(queue.put_nowait, ("stdout", text))
                except Exception as e:
                    logger.debug(f"Logs streaming ended/interrupted: {e}")

            collector_future = loop.run_in_executor(None, collect_logs)

            async def wait_container():
                return await loop.run_in_executor(None, lambda: container.wait(timeout=timeout_sec))

            async def _run_all():
                try:
                    await wait_container()
                except Exception:
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

        except Exception as e:
            logger.error(f"Streaming execution error: {e}", exc_info=True)
            yield "stderr", "Sandbox Execution Error: Unable to launch execution environment."
        finally:
            if bg_task:
                bg_task.cancel()
            if container:
                try:
                    await loop.run_in_executor(None, lambda: container.remove(force=True))
                    logger.debug("🗑️ Ephemeral container destroyed")
                except Exception:
                    pass
