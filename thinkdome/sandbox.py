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
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Union

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result from a sandbox code execution."""

    output: str = ""
    error: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: float = 0.0
    files: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether the execution completed without errors."""
        return self.exit_code == 0 and not self.timed_out

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL(exit={self.exit_code})"
        return f"<SandboxResult {status} duration={self.duration_ms:.0f}ms>"


class Sandbox:
    """Secure code execution sandbox.

    Can be used as a context manager (sync or async) or standalone.

    Args:
        language: Programming language to execute (default: "python").
        timeout: Maximum execution time in seconds (default: 10).
        memory_limit: Maximum memory in MB (default: 128).
        network_allowed: Whether network access is allowed (default: False).
        backend: Execution backend - "auto", "docker", or "subprocess".
            "auto" tries docker first, falls back to subprocess.
        workspace: Path to workspace directory for file I/O.
            If None, creates a temporary directory.
    """

    def __init__(
        self,
        language: str = "python",
        timeout: int = 10,
        memory_limit: int = 128,
        network_allowed: bool = False,
        backend: str = "auto",
        workspace: Optional[str] = None,
    ) -> None:
        self.language = language
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.network_allowed = network_allowed
        self.backend = backend
        self._workspace = workspace
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._executor = None
        self._initialized = False

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
        """Resolve the backend to use ('docker' or 'subprocess')."""
        if self.backend == "auto":
            try:
                import docker
                client = docker.from_env()
                client.ping()
                self.backend = "docker"
                logger.info("ThinkDome: Using Docker executor backend.")
            except Exception:
                self.backend = "subprocess"
                logger.info("ThinkDome: Docker unavailable, using subprocess backend.")
        elif self.backend not in ("docker", "subprocess"):
            raise ValueError(f"Unknown backend: {self.backend!r}. Use 'auto', 'docker', or 'subprocess'.")

    async def _async_init_executor(self) -> None:
        """Initialize the executor asynchronously."""
        from thinkdome.executors.factory import create_executor
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

    def _get_executor_sync(self):
        """Lazily create and initialize the executor synchronously."""
        if self._executor is None:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._async_init_executor())
            finally:
                loop.close()
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

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.arun(code, files=files))
        finally:
            loop.close()

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

        from thinkdome.executors.base import ExecRequest

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
