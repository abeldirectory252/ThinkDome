"""Kubernetes-based Python executor — integrates with the base executor interface."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncGenerator

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.executors.kubernetes_backend import KubernetesBackend
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)


class PythonKubernetesExecutor(BaseExecutor):
    """Executes Python code in isolated Kubernetes pods."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = KubernetesBackend(settings)

    async def initialize(self) -> None:
        """Verify connection to the Kubernetes API."""
        health = await self.backend.health_check()
        if health.status != "healthy":
            raise ConnectionError(f"Kubernetes backend unhealthy: {health.details.get('error')}")

    async def execute(self, request: ExecRequest) -> ExecResult:
        """Run code inside a dynamically created sandbox pod."""
        sandbox_id = f"exec-{uuid.uuid4().hex[:8]}"
        memory_mb = request.memory_limit_mb or self.settings.MEMORY_LIMIT_MB
        cpu_cores = request.cpu_cores or 1.0

        # Create isolated pod sandbox
        handle = await self.backend.create_sandbox(
            sandbox_id=sandbox_id,
            memory_mb=memory_mb,
            cpu_cores=cpu_cores,
            network_enabled=request.allow_network,
        )

        try:
            # Write python script to /workspace/code.py via python base64 decode (safe traversal)
            import base64
            encoded_code = base64.b64encode(request.code.encode("utf-8")).decode("utf-8")
            
            write_cmd = [
                "python3", "-c",
                f"import base64; print('Writing code...'); "
                f"f = open('/workspace/code.py', 'w'); "
                f"f.write(base64.b64decode('{encoded_code}').decode('utf-8')); "
                f"f.close()"
            ]
            await self.backend.execute_in_sandbox(handle, write_cmd)

            # Write stdin if present
            if request.stdin:
                encoded_stdin = base64.b64encode(request.stdin.encode("utf-8")).decode("utf-8")
                write_stdin_cmd = [
                    "python3", "-c",
                    f"import base64; "
                    f"f = open('/workspace/stdin.txt', 'w'); "
                    f"f.write(base64.b64decode('{encoded_stdin}').decode('utf-8')); "
                    f"f.close()"
                ]
                await self.backend.execute_in_sandbox(handle, write_stdin_cmd)

            # Execute python script
            run_cmd = ["python3", "-u", "/workspace/code.py"]
            if request.stdin:
                run_cmd = ["sh", "-c", "python3 -u /workspace/code.py < /workspace/stdin.txt"]

            res = await self.backend.execute_in_sandbox(
                handle,
                run_cmd,
                env_vars=request.env_vars,
                timeout_ms=request.timeout_ms,
            )

            # Fetch output files if request expects it (mock support)
            output_files = {}

            return ExecResult(
                stdout=res.stdout,
                stderr=res.stderr,
                exit_code=res.exit_code,
                timed_out=res.timed_out,
                duration_ms=res.duration_ms,
                output_files=output_files,
            )

        finally:
            # Ensure sandbox pod is cleaned up
            await self.backend.destroy_sandbox(handle)

    async def execute_stream(self, request: ExecRequest) -> AsyncGenerator[tuple[str, str], None]:
        """Run execution and yield stream chunks."""
        res = await self.execute(request)
        if res.stdout:
            yield "stdout", res.stdout
        if res.stderr:
            yield "stderr", res.stderr

    async def shutdown(self) -> None:
        """Shutdown backend connections."""
        pass

    async def health_check(self) -> bool:
        """Check if Kubernetes backend is reachable."""
        health = await self.backend.health_check()
        return health.status == "healthy"
