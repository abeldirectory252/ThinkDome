"""Subprocess-based Python executor for development/testing (less secure)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import AsyncGenerator

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.sandbox.executors.host.bubblewrap import _is_env_var_sensitive

logger = logging.getLogger(__name__)

# Project root for resolving storage paths
_PROJECT_ROOT = Path(__file__).resolve().parents[4]



class SubprocessExecutor(BaseExecutor):
    """Execute Python code via subprocess (dev/test only, NOT for production)."""

    async def initialize(self) -> None:
        logger.warning("WARNING: SubprocessExecutor is NOT secure. Use Docker for production.")

    def _get_user_workspace(self, username: str | None) -> Path | None:
        """Return the persistent workspace directory for a specific user."""
        if not username:
            return None
        namespace = hashlib.sha256(str(username).encode("utf-8")).hexdigest()[:32]
        workspace = _PROJECT_ROOT / "storage" / "workspaces" / namespace
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _get_user_pip_base(self, username: str | None) -> Path | None:
        """Return the PYTHONUSERBASE directory for persistent pip packages."""
        if not username:
            return None
        namespace = hashlib.sha256(str(username).encode("utf-8")).hexdigest()[:32]
        pip_base = _PROJECT_ROOT / "storage" / "workspaces" / namespace / ".pip_packages"
        pip_base.mkdir(parents=True, exist_ok=True)
        return pip_base

    async def execute(self, request: ExecRequest) -> ExecResult:
        start = time.monotonic()
        timeout_sec = request.timeout_ms / 1000.0

        # Determine workspace: persistent (user-specific) or ephemeral (tmpdir)
        user_workspace = self._get_user_workspace(request.username)
        use_persistent = user_workspace is not None

        if use_persistent:
            return await self._execute_in_workspace(request, user_workspace, timeout_sec, start)
        else:
            return await self._execute_ephemeral(request, timeout_sec, start)

    async def _execute_in_workspace(self, request: ExecRequest, workspace: Path, timeout_sec: float, start: float) -> ExecResult:
        """Execute code in a persistent user workspace (Kaggle/Colab-like)."""
        # Write input files
        for path, content in request.files.items():
            fpath = workspace / path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_bytes(content)

        # Write code to file
        code_file = workspace / "__main__.py"
        code_file.write_text(request.code, encoding="utf-8")

        env = self._build_env(request, workspace)

        try:
            result = await self._run_process(request, code_file, workspace, env, timeout_sec)
            # No output file extraction for persistent workspace — files stay in place
            duration_ms = (time.monotonic() - start) * 1000
            return ExecResult(
                stdout=result["stdout"],
                stderr=result["stderr"],
                exit_code=result["exit_code"],
                timed_out=result["timed_out"],
                duration_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            return ExecResult(
                stdout="",
                stderr=f"Subprocess error: {e}",
                exit_code=-1,
                duration_ms=round(duration_ms, 2),
            )
        finally:
            # Clean up the temporary __main__.py but leave everything else
            try:
                code_file.unlink(missing_ok=True)
            except Exception:
                pass

    async def _execute_ephemeral(self, request: ExecRequest, timeout_sec: float, start: float) -> ExecResult:
        """Execute code in a throwaway temp directory."""
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

            env = self._build_env(request, workspace)

            try:
                result = await self._run_process(request, code_file, workspace, env, timeout_sec)

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
                    stdout=result["stdout"],
                    stderr=result["stderr"],
                    exit_code=result["exit_code"],
                    timed_out=result["timed_out"],
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

    def _build_env(self, request: ExecRequest, workspace: Path) -> dict[str, str]:
        """Build environment variables for execution subprocess."""
        env: dict[str, str] = {}
        profile = (request.security_profile or "HIGH_SECURITY").upper()

        if profile == "DEVELOPMENT":
            env = {
                k: v for k, v in os.environ.items()
                if not _is_env_var_sensitive(k)
            }
            logger.warning(
                "⚠️  SubprocessExecutor: DEVELOPMENT profile — host env inherited "
                "with sensitive vars stripped (%d vars removed).",
                len(os.environ) - len(env),
            )
        else:
            # HIGH_SECURITY or ISOLATED: Sanitized environment
            safe_keys = {
                "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR",
                "PATH", "TEMP", "TMP", "TMPDIR",
                "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONUNBUFFERED", "PYTHONPATH",
                "LANG", "LC_ALL", "LC_CTYPE"
            }
            for key in safe_keys:
                if key in os.environ:
                    env[key] = os.environ[key]
            logger.info(f"SubprocessExecutor: Running in {profile} profile. Host environment variables sanitized.")

        # Persistent pip packages: set PYTHONUSERBASE so pip installs persist
        pip_base = self._get_user_pip_base(request.username)
        if pip_base:
            env["PYTHONUSERBASE"] = str(pip_base)
            env["PIP_USER"] = "1"
            # Add the user site-packages bin and lib to PATH/PYTHONPATH
            if sys.platform == "win32":
                site_packages = pip_base / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "site-packages"
                scripts_dir = pip_base / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts"
            else:
                site_packages = pip_base / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
                scripts_dir = pip_base / "bin"

            existing_path = env.get("PATH", "")
            env["PATH"] = f"{scripts_dir}{os.pathsep}{existing_path}" if existing_path else str(scripts_dir)

            existing_pypath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{site_packages}{os.pathsep}{existing_pypath}" if existing_pypath else str(site_packages)

        # Inject explicitly allowed custom environment variables
        if request.env_vars:
            env.update(request.env_vars)

        return env

    async def _run_process(self, request: ExecRequest, code_file: Path, workspace: Path, env: dict, timeout_sec: float) -> dict:
        """Run the code file via subprocess and return stdout/stderr/exit_code/timed_out."""
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

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "timed_out": timed_out,
        }

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Execute Python code via subprocess and stream stdout/stderr in real-time.

        Uses a queue+sentinel pattern: reader tasks push chunks into an
        ``asyncio.Queue`` the moment they arrive from the subprocess pipes.
        The generator yields each chunk immediately, giving the caller
        (and ultimately the browser SSE connection) true real-time output.
        """
        timeout_sec = request.timeout_ms / 1000.0

        user_workspace = self._get_user_workspace(request.username)
        use_persistent = user_workspace is not None

        if use_persistent:
            workspace = user_workspace
        else:
            tmpdir = tempfile.TemporaryDirectory(prefix="thinkbox_")
            workspace = Path(tmpdir.name)

        # Write files
        for path, content in request.files.items():
            fpath = workspace / path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_bytes(content)

        code_file = workspace / "__main__.py"
        code_file.write_text(request.code, encoding="utf-8")

        env = self._build_env(request, workspace)

        # Sentinel object to signal "all reading is done"
        _DONE = object()

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", str(code_file),
                stdin=asyncio.subprocess.PIPE if request.stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace),
                env=env,
            )

            if request.stdin:
                proc.stdin.write(request.stdin.encode())
                await proc.stdin.drain()
                proc.stdin.close()

            queue: asyncio.Queue = asyncio.Queue()

            # ── Readers: push every line into the queue immediately ──
            async def _read_pipe(stream, stream_type: str):
                """Read lines from a pipe and put them into the queue in real-time."""
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    await queue.put((stream_type, line.decode("utf-8", errors="replace")))

            # ── Background orchestrator: run readers + wait for process ──
            async def _run_all():
                stdout_task = asyncio.create_task(_read_pipe(proc.stdout, "stdout"))
                stderr_task = asyncio.create_task(_read_pipe(proc.stderr, "stderr"))

                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    await queue.put(("stderr", "\nProcess timed out.\n"))

                # Wait for readers to drain remaining pipe data
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                # Signal: no more data coming
                await queue.put(_DONE)

            bg_task = asyncio.create_task(_run_all())

            # ── Main loop: yield chunks the instant they arrive ──
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield item
            await bg_task

        finally:
            if 'proc' in locals() and proc:
                try:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                except Exception:
                    pass
            try:
                code_file.unlink(missing_ok=True)
            except Exception:
                pass
            if not use_persistent:
                try:
                    tmpdir.cleanup()
                except Exception:
                    pass
