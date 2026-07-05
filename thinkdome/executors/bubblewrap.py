"""Bubblewrap-based subprocess command executor for Linux OS-level isolation (Anthropic style)."""

from __future__ import annotations

import os
import sys
import asyncio
import logging
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult

logger = logging.getLogger(__name__)


class BubblewrapExecutor(BaseExecutor):
    """Executes commands within a bubblewrap (`bwrap`) user-space namespace sandbox on Linux."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.bwrap_path = "/usr/bin/bwrap"

    async def initialize(self) -> None:
        """Check if bubblewrap is installed on Linux host; log warning otherwise."""
        if sys.platform != "linux":
            logger.warning("Bubblewrap executor is only native to Linux hosts. Operating in compatibility-fallback mode on Windows/macOS.")
            return

        if not os.path.exists(self.bwrap_path):
            # Try searching path
            import shutil
            found = shutil.which("bwrap")
            if found:
                self.bwrap_path = found
            else:
                logger.warning("bubblewrap executable ('bwrap') not found. Command executions will fall back to standard unconfined subprocess execution.")

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        if sys.platform != "linux":
            return True
        import shutil
        return os.path.exists(self.bwrap_path) or shutil.which("bwrap") is not None

    def _build_bwrap_command(self, script_path: Path, workspace_dir: Path) -> list[str]:
        """Construct the bubblewrap shell argument list."""
        cmd = [
            self.bwrap_path,
            # Drop privileges and share namespaces
            "--unshare-all",
            "--uid", "1000",
            "--gid", "1000",
            # Standard directories to share read-only
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin",
            "--ro-bind", "/etc/alternatives", "/etc/alternatives",
        ]

        # Conditionally bind lib64 if it exists
        if os.path.exists("/lib64"):
            cmd.extend(["--ro-bind", "/lib64", "/lib64"])

        # Mount dev, proc, tmpfs
        cmd.extend([
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--tmpfs", "/var",
            # Mount the workspace as the writable sandbox directory
            "--bind", str(workspace_dir), "/workspace",
            "--chdir", "/workspace",
            # Run python
            "python3", "-u", "/workspace/__main__.py"
        ])

        return cmd

    async def execute(self, request: ExecRequest) -> ExecResult:
        start = time.monotonic()
        timeout_sec = request.timeout_ms / 1000.0

        # Create temporary workspace directory for file and script staging
        temp_dir = tempfile_create()
        workspace_dir = Path(temp_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Write input files
            for path, content in request.files.items():
                fpath = workspace_dir / path
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_bytes(content)

            # Write code to run
            script_path = workspace_dir / "__main__.py"
            script_path.write_text(request.code, encoding="utf-8")

            # Environment variables filtering (Credential protection unsetting)
            env = dict(os.environ)
            # Apply custom env vars
            if request.env_vars:
                env.update(request.env_vars)

            # Enforce unsetting of blocked environment variables
            if request.security_profile == "HIGH_SECURITY":
                blocked_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "DATABASE_URL", "SECRET_KEY", "API_KEY", "JWT_SECRET"]
                for var in blocked_vars:
                    env.pop(var, None)

            # Determine execution command
            if sys.platform == "linux" and os.path.exists(self.bwrap_path):
                args = self._build_bwrap_command(script_path, workspace_dir)
                logger.info(f"🔒 Executing command inside bubblewrap jail: {' '.join(args[:10])}...")
            else:
                # Compatibility mode (standard subprocess)
                args = [sys.executable, "-u", str(script_path)]
                logger.warning(f"⚠️ Falling back to standard execution runner on current OS: {sys.platform}")

            # Spawn subprocess
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if request.stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace_dir) if sys.platform != "linux" else None,
                env=env
            )

            # Handle stdin input
            try:
                stdin_data = request.stdin.encode("utf-8") if request.stdin else None
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(input=stdin_data),
                    timeout=timeout_sec
                )
                timed_out = False
                exit_code = process.returncode if process.returncode is not None else 0
            except asyncio.TimeoutError:
                # Timeout enforcement (SIGKILL equivalent)
                try:
                    process.kill()
                except Exception:
                    pass
                stdout_bytes, stderr_bytes = await process.communicate()
                timed_out = True
                exit_code = -1

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:request.max_output_bytes]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:request.max_output_bytes]

            duration_ms = (time.monotonic() - start) * 1000

            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=round(duration_ms, 2)
            )

        finally:
            # Clean up ephemeral workspace
            try:
                import shutil
                shutil.rmtree(str(workspace_dir), ignore_errors=True)
            except Exception:
                pass

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Stream execution output — falls through to batch execute for bubblewrap."""
        result = await self.execute(request)
        if result.stdout:
            yield ("stdout", result.stdout)
        if result.stderr:
            yield ("stderr", result.stderr)


def tempfile_create() -> str:
    import tempfile
    return tempfile.mkdtemp(prefix="thinkdome_bwrap_")
