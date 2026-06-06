"""Subprocess-based Python executor for development/testing (less secure)."""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult

logger = logging.getLogger(__name__)


class SubprocessExecutor(BaseExecutor):
    """Execute Python code via subprocess (dev/test only, NOT for production)."""

    async def initialize(self) -> None:
        logger.warning("WARNING: SubprocessExecutor is NOT secure. Use Docker for production.")

    async def execute(self, request: ExecRequest) -> ExecResult:
        start = time.monotonic()
        timeout_sec = request.timeout_ms / 1000.0

        with tempfile.TemporaryDirectory(prefix="thinkbox_") as tmpdir:
            workspace = Path(tmpdir)

            # Write input files
            for path, content in request.files.items():
                fpath = workspace / path
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_bytes(content)

            # Write code to file
            code_file = workspace / "__main__.py"
            code_file.write_text(request.code, encoding="utf-8")

            # Build execution environment based on security profile
            import os
            env = {}
            profile = (request.security_profile or "HIGH_SECURITY").upper()

            if profile == "DEVELOPMENT":
                # Inherit full environment (classic behavior, not secure)
                env = dict(os.environ)
                logger.warning(
                    "âš ï¸  SubprocessExecutor: Running in DEVELOPMENT profile. "
                    "All host environment variables are inherited!"
                )
            else:
                # HIGH_SECURITY or ISOLATED: Zero-inheritance (Sanitized Environment)
                # Keep only safe, essential system vars to let python/OS run correctly
                safe_keys = {
                    # Windows essentials
                    "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR",
                    # Common path/temp vars
                    "PATH", "TEMP", "TMP", "TMPDIR",
                    # Python configuration variables
                    "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONUNBUFFERED", "PYTHONPATH",
                    # Locale settings
                    "LANG", "LC_ALL", "LC_CTYPE"
                }
                for key in safe_keys:
                    if key in os.environ:
                        env[key] = os.environ[key]
                logger.info(f"SubprocessExecutor: Running in {profile} profile. Host environment variables sanitized.")

            # Inject explicitly allowed custom environment variables
            if request.env_vars:
                env.update(request.env_vars)

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", str(code_file),
                    stdin=asyncio.subprocess.PIPE if request.stdin else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(workspace),
                    env=env,
                )

                stdin_bytes = request.stdin.encode() if request.stdin else None

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(input=stdin_bytes),
                        timeout=timeout_sec,
                    )
                    timed_out = False
                    exit_code = proc.returncode or 0
                except asyncio.TimeoutError:
                    proc.kill()
                    stdout_bytes, stderr_bytes = await proc.communicate()
                    timed_out = True
                    exit_code = -1

                stdout = stdout_bytes.decode("utf-8", errors="replace")[: request.max_output_bytes]
                stderr = stderr_bytes.decode("utf-8", errors="replace")[: request.max_output_bytes]

                # Collect output files
                output_files: dict[str, bytes] = {}
                input_names = set(request.files.keys()) | {"__main__.py"}
                for fpath in workspace.rglob("*"):
                    if fpath.is_file():
                        rel = str(fpath.relative_to(workspace))
                        if rel not in input_names:
                            output_files[rel] = fpath.read_bytes()

                duration_ms = (time.monotonic() - start) * 1000
                return ExecResult(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    timed_out=timed_out,
                    duration_ms=round(duration_ms, 2),
                    output_files=output_files,
                )

            except Exception as e:
                duration_ms = (time.monotonic() - start) * 1000
                return ExecResult(
                    stdout="",
                    stderr=f"Subprocess error: {e}",
                    exit_code=-1,
                    duration_ms=round(duration_ms, 2),
                )

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True
