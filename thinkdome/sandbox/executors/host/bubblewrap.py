"""Bubblewrap-based subprocess command executor for Linux OS-level isolation (Anthropic style)."""

from __future__ import annotations

import os
import sys
import asyncio
import logging
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult

logger = logging.getLogger(__name__)

# ── Environment Sanitization ────────────────────────────────────────────
# Allowlist: only these host env vars are safe to propagate into sandboxes.
_SAFE_ENV_KEYS = frozenset({
    "PATH", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE",
    "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONUNBUFFERED", "PYTHONPATH",
    # Windows compat (harmless on Linux)
    "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR",
})

# Blocklist patterns: env vars matching these prefixes are ALWAYS stripped,
# even when running in DEVELOPMENT profile. Case-insensitive prefix match.
_BLOCKED_ENV_PREFIXES = (
    "AWS_", "AZURE_", "GCP_", "GOOGLE_APPLICATION",
    "ANTIGRAVITY_",
    "DOCKER_", "KUBERNETES_", "K8S_",
    "VAULT_", "CONSUL_",
    "DATABASE_URL", "DB_",
    "JWT_", "CSRF_",
)

_BLOCKED_ENV_SUBSTRINGS = (
    "SECRET", "TOKEN", "CREDENTIAL", "PASSWORD", "PASSWD",
    "API_KEY", "PRIVATE_KEY", "ACCESS_KEY",
)


def _is_env_var_sensitive(key: str) -> bool:
    """Return True if an environment variable name looks sensitive."""
    upper = key.upper()
    for prefix in _BLOCKED_ENV_PREFIXES:
        if upper.startswith(prefix):
            return True
    for substr in _BLOCKED_ENV_SUBSTRINGS:
        if substr in upper:
            return True
    return False


def _build_safe_env(
    security_profile: str,
    custom_env_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized environment dict for sandboxed subprocess execution.

    HIGH_SECURITY / ISOLATED (default):
        Start from an empty env, copy only _SAFE_ENV_KEYS from the host.

    DEVELOPMENT:
        Start from the full host env, then strip anything matching the
        blocklist prefixes/substrings.
    """
    profile = (security_profile or "HIGH_SECURITY").upper()

    if profile == "DEVELOPMENT":
        env = {
            k: v for k, v in os.environ.items()
            if not _is_env_var_sensitive(k)
        }
        logger.warning(
            "⚠️  BubblewrapExecutor: DEVELOPMENT profile — host env inherited "
            "with sensitive vars stripped (%d vars removed).",
            len(os.environ) - len(env),
        )
    else:
        env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
        logger.info(
            "BubblewrapExecutor: %s profile — allowlist-only env (%d vars).",
            profile, len(env),
        )

    # Merge caller-supplied custom env vars (vault secrets, user-specified)
    if custom_env_vars:
        env.update(custom_env_vars)

    return env


class BubblewrapExecutor(BaseExecutor):
    """Executes commands within a bubblewrap (`bwrap`) user-space namespace sandbox on Linux."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.bwrap_path = "/usr/bin/bwrap"
        self._bwrap_usable = False

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
                return

        # Presence of the binary is insufficient: hardened hosts may deny
        # user/network namespace creation. Probe once so execution does not
        # burn the user's timeout and report a misleading timeout error.
        import subprocess
        try:
            probe = subprocess.run(
                [self.bwrap_path, "--unshare-all", "--die-with-parent",
                 "--ro-bind", "/usr", "/usr", "--proc", "/proc",
                 "--dev", "/dev", "--tmpfs", "/tmp", "--", "/bin/true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=1.0, check=False,
            )
            self._bwrap_usable = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            self._bwrap_usable = False
        if not self._bwrap_usable:
            logger.warning("bubblewrap is installed but unavailable under this host's namespace policy; using compatibility fallback")

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        if sys.platform != "linux":
            return True
        import shutil
        return self._bwrap_usable

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

            # Build sanitized environment — allowlist for HIGH_SECURITY,
            # blocklist-filtered for DEVELOPMENT.
            env = _build_safe_env(
                security_profile=request.security_profile,
                custom_env_vars=request.env_vars,
            )

            # Determine execution command
            if sys.platform == "linux" and self._bwrap_usable:
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
