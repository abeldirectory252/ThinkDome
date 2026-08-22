"""ThinkDome Sandbox - Simple, Pythonic code execution API.

Usage::

    from thinkdome import Sandbox

    # Basic usage
    with Sandbox() as dome:
        result = dome.run("print('Hello from ThinkDome!')")
        print(result.output)

    # With custom limits
    with Sandbox(timeout=30, memory_limit=256, network_allowed=False) as dome:
        result = dome.run(user_code)

    # Async usage
    async with Sandbox() as dome:
        result = await dome.arun("print('async hello')")
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, List, Union

from datetime import timedelta
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CredentialProxyConfig(BaseModel):
    """Configuration for Credential Proxy injection."""
    enabled: bool = Field(True, description="Whether Credential Proxy is enabled for outbound requests")


class SandboxImageSpec(BaseModel):
    """Container image specification for sandbox creation."""
    uri: str = Field(..., description="Container image URI, e.g. 'python:3.11' or 'opensandbox/code-interpreter'")


@dataclass
class SandboxResult:
    """Result from a sandbox code execution."""

    output: str = ""
    error: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: float = 0.0
    files: dict = field(default_factory=dict)
    error_code: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether the execution completed without errors."""
        return self.exit_code == 0 and not self.timed_out

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL(exit={self.exit_code})"
        return f"<SandboxResult {status} duration={self.duration_ms:.0f}ms>"


class Sandbox:
    """Secure code execution sandbox matching OpenSandbox developer API conventions.

    Can be created via Sandbox.create(...) or used as a context manager.
    """

    def __init__(
        self,
        image: Optional[Union[str, SandboxImageSpec]] = None,
        timeout: Union[int, float, timedelta] = 10,
        network_policy: Optional[Any] = None,
        credential_proxy: Optional[Union[CredentialProxyConfig, bool]] = None,
        env: Optional[dict] = None,
        metadata: Optional[dict] = None,
        language: str = "python",
        memory_limit: int = 128,
        network_allowed: bool = False,
        backend: str = "auto",
        workspace: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        api_key: Optional[str] = None,
        purpose: str = "general",
        template: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        import uuid
        import os

        # API Key authentication & Purpose scoping
        self.api_key = api_key or os.getenv("THINKDOME_API_KEY") or os.getenv("THINKBOX_API_KEY")
        self.purpose = purpose
        self.template = template
        self.ttl = ttl

        # Image handling
        if isinstance(image, SandboxImageSpec):
            self.image = image.uri
        else:
            self.image = image or "thinkdome-executor:latest"

        # Timeout handling (supports timedelta or int seconds)
        if isinstance(timeout, timedelta):
            self.timeout = int(timeout.total_seconds())
        else:
            self.timeout = int(timeout)

        self.language = language
        self.memory_limit = memory_limit
        self.backend = backend
        self.env = env or {}
        self.metadata = metadata or {}
        if purpose:
            self.metadata["purpose"] = purpose
        if template:
            self.metadata["template"] = template
            
        self.sandbox_id = sandbox_id or f"sb_{uuid.uuid4().hex[:8]}"
        self._workspace = workspace
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._executor = None
        self._initialized = False
        self._snapshot_service = None

        # Network Policy & Ingress/Egress Controls
        from thinkdome.sandbox.network.policy import get_default_network_policy, NetworkPolicy
        from thinkdome.sandbox.network.ingress import IngressGateway
        from thinkdome.sandbox.network.egress import EgressProxy, EgressRule

        self.egress_proxy = EgressProxy()
        self.ingress_gateway = IngressGateway()

        if network_policy is not None:
            self.network_policy = network_policy
            # If a custom policy with egress rules was provided, enable network & sync rules
            if getattr(network_policy, "egress", None):
                self.network_allowed = True
                for r in network_policy.egress:
                    if r.action == "allow":
                        escaped_target = re.escape(r.target).replace("\\*", ".*")
                        pattern = f".*{escaped_target}$" if "*" in r.target else f"{escaped_target}$"
                        self.egress_proxy.add_rule(EgressRule(
                            domain_pattern=pattern,
                            description=f"User policy rule for {r.target}",
                        ))
            else:
                self.network_allowed = (getattr(network_policy, "default_action", "deny") == "allow")
        else:
            self.network_policy = get_default_network_policy()
            # Network is deny-by-default.  Callers must explicitly opt in via
            # a network policy or ``network_allowed=True``; do not let a
            # boolean expression silently turn every sandbox into an egress
            # request.
            self.network_allowed = bool(network_allowed)

        # Credential Proxy / Vault
        self.credential_proxy_enabled = False
        if credential_proxy:
            if isinstance(credential_proxy, CredentialProxyConfig):
                self.credential_proxy_enabled = credential_proxy.enabled
            else:
                self.credential_proxy_enabled = bool(credential_proxy)

    def get_sandbox_token(self, expires_minutes: int = 5) -> str:
        """Mint a short-lived single-sandbox access token for browser log streaming or sidecar execution."""
        from thinkdome.security.auth.single_sandbox_token import mint_sandbox_access_token
        return mint_sandbox_access_token(
            sandbox_id=self.sandbox_id,
            username="sdk_client",
            role="AGENT_STANDARD",
            expires_minutes=expires_minutes
        )

    @classmethod
    def create(
        cls,
        image: Optional[Union[str, SandboxImageSpec]] = None,
        timeout: Union[int, float, timedelta] = 10,
        network_policy: Optional[Any] = None,
        credential_proxy: Optional[Union[CredentialProxyConfig, bool]] = None,
        env: Optional[dict] = None,
        metadata: Optional[dict] = None,
        language: str = "python",
        memory_limit: int = 128,
        backend: str = "auto",
        workspace: Optional[str] = None,
        sandbox_id: Optional[str] = None,
    ) -> "Sandbox":
        """Create and initialize a Sandbox instance matching OpenSandbox creation style."""
        sb = cls(
            image=image,
            timeout=timeout,
            network_policy=network_policy,
            credential_proxy=credential_proxy,
            env=env,
            metadata=metadata,
            language=language,
            memory_limit=memory_limit,
            backend=backend,
            workspace=workspace,
            sandbox_id=sandbox_id,
        )
        sb._setup()
        return sb

    @property
    def snapshot_service(self):
        if self._snapshot_service is None:
            from thinkdome.sandbox.snapshots.service import SnapshotService
            self._snapshot_service = SnapshotService()
        return self._snapshot_service

    @property
    def workspace(self) -> Path:
        """Return the active workspace directory."""
        if self._workspace:
            return Path(self._workspace)
        if self._temp_dir:
            return Path(self._temp_dir.name)
        return Path(tempfile.gettempdir()) / "thinkdome-workspace"

    # ── Sync Context Manager ──

    def __enter__(self) -> "Sandbox":
        self._setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._teardown()

    # ── Async Context Manager ──

    async def __aenter__(self) -> "Sandbox":
        self._setup()
        await self._async_init_executor()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._executor:
            await self._executor.shutdown()
        self._teardown()

    # ── Setup / Teardown ──

    def _setup(self) -> None:
        """Initialize workspace and executor."""
        if not self._workspace:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="thinkdome_")
        os.makedirs(str(self.workspace), exist_ok=True)
        self._resolve_backend()
        self._initialized = True

    def _teardown(self) -> None:
        """Clean up resources."""
        if self._temp_dir:
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            self._temp_dir = None
        self._initialized = False

    def _resolve_backend(self) -> None:
        """Resolve the backend to use ('microvm', 'docker', or 'subprocess').

        Auto-detection priority:
          1. MicroVM — requires /dev/kvm + cloud-hypervisor binary
          2. Docker  — requires Docker daemon accessible
          3. subprocess — always available (least isolation)
        """
        if self.backend == "auto":
            # 1. Try MicroVM (hardware-isolated)
            import shutil
            if os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK) and shutil.which("cloud-hypervisor"):
                self.backend = "microvm"
                logger.info("ThinkDome: Using MicroVM executor backend (KVM + Cloud Hypervisor).")
                return

            # 2. Try Docker (container-isolated)
            try:
                import docker
                client = docker.from_env()
                client.ping()
                self.backend = "docker"
                logger.info("ThinkDome: Using Docker executor backend.")
                return
            except Exception:
                pass

            # 3. Fallback to subprocess (least isolation)
            self.backend = "subprocess"
            logger.info("ThinkDome: No MicroVM or Docker available, using subprocess backend.")
        elif self.backend not in ("docker", "subprocess", "microvm", "hybrid", "kubernetes"):
            raise ValueError(f"Unknown backend: {self.backend!r}. Use 'auto', 'microvm', 'docker', 'subprocess', 'hybrid', or 'kubernetes'.")

    async def _async_init_executor(self) -> None:
        """Initialize the executor asynchronously."""
        from thinkdome.sandbox.executors.factory import create_executor
        from thinkdome.core.config import Settings

        os.environ.setdefault("EXECUTOR_BACKEND", self.backend)
        os.environ.setdefault("MAX_EXEC_TIMEOUT_MS", str(self.timeout * 1000))
        os.environ.setdefault("MEMORY_LIMIT_MB", str(self.memory_limit))

        settings = Settings()
        settings.EXECUTOR_BACKEND = self.backend
        settings.MAX_EXEC_TIMEOUT_MS = self.timeout * 1000
        settings.MEMORY_LIMIT_MB = self.memory_limit

        self._executor = create_executor(settings, self.language)
        await self._executor.initialize()

    def _run_sync(self, coro):
        """Run an async coroutine synchronously, supporting running event loops (e.g. Jupyter)."""
        import threading
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            result = []
            exception = []
            
            def worker():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    res = new_loop.run_until_complete(coro)
                    result.append(res)
                except Exception as e:
                    exception.append(e)
                finally:
                    new_loop.close()
                    
            t = threading.Thread(target=worker)
            t.start()
            t.join()
            if exception:
                raise exception[0]
            return result[0]
        else:
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

    def _get_executor_sync(self):
        """Lazily create and initialize the executor synchronously."""
        if self._executor is None:
            self._run_sync(self._async_init_executor())
        return self._executor

    # ── Execution API ──

    def run(self, code: str, files: Optional[dict] = None) -> SandboxResult:
        """Execute code synchronously in the sandbox.

        Args:
            code: Source code string to execute.
            files: Optional dict of {filename: content_bytes} to place in workspace.

        Returns:
            SandboxResult with output, error, exit_code, etc.
        """
        if not self._initialized:
            self._setup()

        return self._run_sync(self.arun(code, files=files))

    async def arun(self, code: str, files: Optional[dict] = None) -> SandboxResult:
        """Execute code asynchronously in the sandbox.

        Args:
            code: Source code string to execute.
            files: Optional dict of {filename: content_bytes} to place in workspace.

        Returns:
            SandboxResult with output, error, exit_code, etc.
        """
        if not self._initialized:
            self._setup()

        executor = self._executor
        if executor is None:
            await self._async_init_executor()
            executor = self._executor

        from thinkdome.sandbox.executors.base import ExecRequest

        exec_files = {}
        
        # 1. Read files already present in the workspace directory
        if self.workspace.exists():
            for p in self.workspace.rglob("*"):
                if p.is_file():
                    rel_path = str(p.relative_to(self.workspace)).replace("\\", "/")
                    try:
                        exec_files[rel_path] = p.read_bytes()
                    except Exception as e:
                        logger.warning(f"Could not read workspace file {rel_path}: {e}")

        # 2. Merge/overwrite with files passed explicitly to run
        if files:
            for fname, content in files.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                exec_files[fname.replace("\\", "/")] = content

        request = ExecRequest(
            code=code,
            timeout_ms=self.timeout * 1000,
            files=exec_files,
            allow_network=self.network_allowed,
            env_vars=self.env,
        )

        result = await executor.execute(request)

        # 3. Write new output files back to the workspace directory
        if result.output_files:
            for fname, content in result.output_files.items():
                if fname == "__main__.py":
                    continue
                out_path = self.workspace / fname
                try:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(content)
                except Exception as e:
                    logger.warning(f"Could not write output file {fname} back to workspace: {e}")

        return SandboxResult(
            output=result.stdout,
            error=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration_ms=result.duration_ms,
            files=result.output_files,
            error_code=result.error_code,
        )

    def install(self, packages: List[str]) -> SandboxResult:
        """Install Python packages inside the sandbox.

        Args:
            packages: List of package names to install.

        Returns:
            SandboxResult from the pip install command.
        """
        install_code = f"import subprocess; subprocess.check_call(['pip', 'install', {', '.join(repr(p) for p in packages)}])"
        return self.run(install_code)

    # ── Convenience Methods ──

    def read_file(self, path: str) -> str:
        """Read a file from the workspace as text."""
        full_path = self.workspace / path
        return full_path.read_text(encoding="utf-8")

    def read_file_bytes(self, path: str) -> bytes:
        """Read a file from the workspace as binary bytes (useful for images/media)."""
        full_path = self.workspace / path
        return full_path.read_bytes()

    def write_file(self, path: str, content: Union[str, bytes]) -> None:
        """Write a text or binary file to the workspace."""
        full_path = self.workspace / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            full_path.write_bytes(content)
        else:
            full_path.write_text(content, encoding="utf-8")

    def list_files(self, path: str = ".") -> List[str]:
        """List files in a workspace subdirectory."""
        full_path = self.workspace / path
        if not full_path.exists():
            return []
        return [str(p.relative_to(full_path)) for p in full_path.rglob("*") if p.is_file()]

    # ── Snapshot & Backtrack SDK API ──

    def snapshot(self, tag: Optional[str] = None, description: str = "") -> str:
        """Create a point-in-time snapshot checkpoint of the sandbox state and workspace."""
        if not self._initialized:
            self._setup()
        meta = self.snapshot_service.create_snapshot(
            sandbox_id=self.sandbox_id,
            tag=tag,
            description=description,
            workspace_path=str(self.workspace),
        )
        return meta["snapshot_id"]

    def restore(self, snapshot_id: str) -> bool:
        """Restore the sandbox state back to a specific snapshot checkpoint."""
        res = self.snapshot_service.restore_snapshot(
            sandbox_id=self.sandbox_id,
            snapshot_id=snapshot_id,
            workspace_path=str(self.workspace),
        )
        return res["success"]

    def list_snapshots(self) -> List[dict]:
        """List all snapshot checkpoints for this sandbox."""
        return self.snapshot_service.list_snapshots(sandbox_id=self.sandbox_id)

    def backtrack(self) -> bool:
        """Backtrack the sandbox to its most recent snapshot checkpoint."""
        res = self.snapshot_service.backtrack_to_last(
            sandbox_id=self.sandbox_id,
            workspace_path=str(self.workspace),
        )
        return res["success"]
