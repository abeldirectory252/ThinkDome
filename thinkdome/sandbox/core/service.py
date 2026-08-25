"""Execution orchestration service."""

from __future__ import annotations

import base64
import logging
import time
from typing import AsyncGenerator, Optional

from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.base import BaseExecutor, ExecRequest, ExecResult
from thinkdome.sandbox.executors.factory import create_executor
from thinkdome.sandbox.core.models import (
    ExecuteRequest,
    ExecuteResponse,
    FileInput,
    FileOutput,
    BatchExecuteRequest,
    BatchExecuteResponse,
)
from thinkdome.sandbox.core.utils import wrap_last_expression
from thinkdome.platform.storage.utils import decode_base64

from thinkdome.security.identity.core import UserIdentity

logger = logging.getLogger(__name__)


class ExecutionService:
    """Orchestrates code execution lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._executors: dict[str, BaseExecutor] = {}
        from thinkdome.sandbox.snapshots.service import SnapshotService
        self.snapshot_service = SnapshotService(settings)

    async def initialize(self) -> None:
        """Initialize default executor.

        Development-only fallback chain (only active when explicitly enabled):
          - microvm fails (no /dev/kvm) → subprocess
          - docker fails (no daemon)    → subprocess
        """
        try:
            executor = create_executor(self.settings, "python")
            await executor.initialize()
            self._executors["python"] = executor
        except Exception as e:
            backend = self.settings.EXECUTOR_BACKEND.lower()
            if backend in ("docker", "microvm"):
                if backend == "microvm" and self.settings.allows_insecure_execution_fallback():
                    try:
                        logger.warning(
                            "MicroVM initialization failed (%s). Attempting auto-fallback to Docker backend.", e
                        )
                        self.settings.EXECUTOR_BACKEND = "docker"
                        executor = create_executor(self.settings, "python")
                        await executor.initialize()
                        self._executors["python"] = executor
                        logger.info("Successfully initialized Docker backend as fallback.")
                        return
                    except Exception as docker_exc:
                        logger.warning("Docker fallback also failed: %s", docker_exc)

                if self.settings.allows_insecure_execution_fallback():
                    logger.warning("Using explicitly enabled development subprocess fallback.")
                    self.settings.EXECUTOR_BACKEND = "subprocess"
                    executor = create_executor(self.settings, "python")
                    await executor.initialize()
                    self._executors["python"] = executor
                    return

            logger.error(
                f"Failed to initialize {backend} executor: {e} "
                f"(insecure_fallback_allowed={self.settings.allows_insecure_execution_fallback()})"
            )
            raise

        logger.info(
            "ExecutionService initialized (backend=%s)",
            self.settings.EXECUTOR_BACKEND,
        )

    def _get_executor(self, language: str) -> BaseExecutor:
        language = language.lower()
        if language not in self._executors:
            executor = create_executor(self.settings, language)
            self._executors[language] = executor
        return self._executors[language]

    async def _ensure_executor(self, language: str) -> BaseExecutor:
        executor = self._get_executor(language)
        try:
            if not await executor.health_check():
                await executor.initialize()
            return executor
        except Exception as e:
            backend = self.settings.EXECUTOR_BACKEND.lower()
            if self.settings.allows_insecure_execution_fallback() and backend in ("docker", "microvm"):
                logger.warning(
                    f"{backend} executor health check/init failed for {language}: {e}. "
                    "Falling back to subprocess execution backend."
                )
                self.settings.EXECUTOR_BACKEND = "subprocess"
                if language in self._executors:
                    del self._executors[language]
                executor = self._get_executor(language)
                await executor.initialize()
                return executor
            else:
                raise

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """Execute a single code request."""
        executor = await self._ensure_executor(request.language)

        # Prepare code
        code = request.code
        if request.last_line_interactive:
            code = wrap_last_expression(code)

        # Prepare files
        files: dict[str, bytes] = {}
        for f in request.files:
            content = self._resolve_file(f)
            if content is not None:
                files[f.path] = content

        # Enforce limits: cap at MAX_EXEC_TIMEOUT_MS unless sandbox limits are active or user is admin
        is_admin_caller = UserIdentity.from_dict({"role": request.caller_role}).is_admin() if request.caller_role else False
        caller_role = (request.caller_role or "").upper()
        can_customize_resources = is_admin_caller or caller_role in {"ORCH", "IDE"}
        if can_customize_resources:
            timeout_ms = request.timeout_ms
        else:
            timeout_ms = min(request.timeout_ms, self.settings.MAX_EXEC_TIMEOUT_MS)

        exec_req = ExecRequest(
            code=code,
            language=request.language,
            stdin=request.stdin,
            timeout_ms=timeout_ms,
            files=files,
            memory_limit_mb=request.memory_limit_mb if can_customize_resources else None,
            cpu_time_limit_sec=self.settings.CPU_TIME_LIMIT_SEC,
            max_output_bytes=self.settings.MAX_OUTPUT_BYTES,
            security_profile=request.security_profile,
            env_vars=request.env_vars,
            caller_role=request.caller_role,
            allow_network=request.allow_network,
            cpu_cores=request.cpu_cores if can_customize_resources else None,
            username=request.username,
        )

        result = await executor.execute(exec_req)

        # Convert output files
        output_files = [
            FileOutput(
                path=path,
                content_base64=base64.b64encode(content).decode("utf-8"),
                size_bytes=len(content),
            )
            for path, content in result.output_files.items()
        ]

        return ExecuteResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration_ms=result.duration_ms,
            files=output_files,
            error_code=result.error_code,
        )

    async def execute_batch(self, request: BatchExecuteRequest) -> BatchExecuteResponse:
        """Execute multiple code blocks sequentially."""
        results = []
        total_start = time.monotonic()

        for exec_req in request.executions:
            resp = await self.execute(exec_req)
            results.append(resp)
            # Stop batch on error if exit_code != 0
            if resp.exit_code != 0:
                break

        total_duration = (time.monotonic() - total_start) * 1000
        return BatchExecuteResponse(
            results=results,
            total_duration_ms=round(total_duration, 2),
        )

    async def execute_stream(self, request: ExecuteRequest) -> AsyncGenerator[dict, None]:
        """Stream execution — for SSE. Runs execution and yields output chunks in real-time.

        Yields dicts consumed by sse-starlette's EventSourceResponse.
        Each dict has a 'data' key whose value is the JSON-serialised event payload.
        """
        import json

        yield {"data": json.dumps({'event': 'start', 'language': request.language})}

        executor = await self._ensure_executor(request.language)

        # Prepare code
        code = request.code
        if request.last_line_interactive:
            code = wrap_last_expression(code)

        # Prepare files
        files: dict[str, bytes] = {}
        for f in request.files:
            content = self._resolve_file(f)
            if content is not None:
                files[f.path] = content

        # Enforce limits
        is_admin_caller = UserIdentity.from_dict({"role": request.caller_role}).is_admin() if request.caller_role else False
        caller_role = (request.caller_role or "").upper()
        can_customize_resources = is_admin_caller or caller_role in {"ORCH", "IDE"}
        if can_customize_resources:
            timeout_ms = request.timeout_ms
        else:
            timeout_ms = min(request.timeout_ms, self.settings.MAX_EXEC_TIMEOUT_MS)

        exec_req = ExecRequest(
            code=code,
            language=request.language,
            stdin=request.stdin,
            timeout_ms=timeout_ms,
            files=files,
            memory_limit_mb=request.memory_limit_mb if can_customize_resources else None,
            cpu_time_limit_sec=self.settings.CPU_TIME_LIMIT_SEC,
            max_output_bytes=self.settings.MAX_OUTPUT_BYTES,
            security_profile=request.security_profile,
            env_vars=request.env_vars,
            caller_role=request.caller_role,
            allow_network=request.allow_network,
            cpu_cores=request.cpu_cores if can_customize_resources else None,
            username=request.username,
        )

        exit_code = 0
        try:
            async for stream_type, chunk in executor.execute_stream(exec_req):
                if stream_type == "error":
                    exit_code = 1
                yield {"data": json.dumps({'event': stream_type, 'data': chunk})}
            yield {"data": json.dumps({'event': 'done', 'exit_code': exit_code, 'duration_ms': 0.0, 'timed_out': False})}
        except Exception as e:
            yield {"data": json.dumps({'event': 'stderr', 'data': f'Streaming error: {e}'})}
            yield {"data": json.dumps({'event': 'done', 'exit_code': -1, 'duration_ms': 0.0, 'timed_out': False})}

    def _resolve_file(self, f: FileInput) -> Optional[bytes]:
        """Resolve file content from base64 or file_id."""
        if f.content_base64:
            return decode_base64(f.content_base64)
        if f.file_id:
            # TODO: look up file from FileService storage
            logger.warning(f"file_id resolution not yet connected: {f.file_id}")
            return None
        return None

    async def health_check(self) -> dict:
        """Check health of all executors."""
        results = {}
        for lang, executor in self._executors.items():
            results[lang] = await executor.health_check()
        return results

    async def shutdown(self) -> None:
        """Shutdown all executors."""
        for lang, executor in self._executors.items():
            await executor.shutdown()
            logger.info(f"Executor '{lang}' shut down")
