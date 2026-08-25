"""Stateful session management for REPL-like execution."""

from __future__ import annotations

import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from thinkdome.core.config import Settings
from thinkdome.sandbox.sessions.models import (
    CreateSessionRequest,
    SessionInfo,
    SessionExecRequest,
    SessionExecResponse,
)
from thinkdome.sandbox.core.models import ExecuteRequest
from thinkdome.sandbox.core.service import ExecutionService

logger = logging.getLogger(__name__)


class SessionService:
    """Manages stateful execution sessions."""

    def __init__(self, settings: Settings, execution_service: ExecutionService) -> None:
        self.settings = settings
        self.execution_service = execution_service
        self._sessions: dict[str, SessionInfo] = {}
        self._history: dict[str, list[str]] = {}  # session_id -> list of code blocks
        self._locks: dict[str, asyncio.Lock] = {}
        self._max_history_blocks = 100
        self._max_history_chars = 1_000_000

    def create(self, request: CreateSessionRequest, owner_id: str | None = None) -> SessionInfo:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        info = SessionInfo(
            session_id=session_id,
            language=request.language,
            status="active",
            created_at=now,
            last_activity=now,
            owner_id=owner_id,
        )
        self._sessions[session_id] = info
        self._history[session_id] = []
        self._locks[session_id] = asyncio.Lock()
        logger.info(f"Session created: {session_id}")
        return info

    def get(self, session_id: str, owner_id: str | None = None) -> Optional[SessionInfo]:
        session = self._sessions.get(session_id)
        return session if session and (owner_id is None or session.owner_id == owner_id) else None

    async def execute_in_session(
        self, session_id: str, request: SessionExecRequest, owner_id: str | None = None
    ) -> Optional[SessionExecResponse]:
        session = self.get(session_id, owner_id)
        if not session or session.status != "active":
            return None

        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            if session.status != "active":
                return None
            # Serialize executions per session and bound retained code so a
            # long-lived session cannot exhaust API-worker memory.
            history = self._history.setdefault(session_id, [])
            history.append(request.code)
            if len(history) > self._max_history_blocks:
                del history[:-self._max_history_blocks]
            full_code = "\n".join(history)

            if len(full_code) > self._max_history_chars:
                # Keep the newest code block and discard older context rather
                # than allowing request volume to grow without bound.
                history[:] = [request.code]
                full_code = request.code

            exec_request = ExecuteRequest(
                code=full_code,
                language=session.language,
                timeout_ms=request.timeout_ms,
                last_line_interactive=request.last_line_interactive,
                username=owner_id,
            )

            result = await self.execution_service.execute(exec_request)

            session.last_activity = datetime.now(timezone.utc)
            session.execution_count += 1

            return SessionExecResponse(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                duration_ms=result.duration_ms,
                execution_index=session.execution_count,
            )

    def close(self, session_id: str, owner_id: str | None = None) -> bool:
        session = self.get(session_id, owner_id)
        if not session:
            return False
        session.status = "closed"
        self._history.pop(session_id, None)
        # Keep the lock object stable for executions already waiting on it.
        # Removing it here would let a late request create a second lock and
        # race the in-flight execution during close.
        return True

    async def cleanup_all(self) -> None:
        """Close all active sessions."""
        for sid in list(self._sessions.keys()):
            self.close(sid)
            self._locks.pop(sid, None)
        logger.info("All sessions cleaned up")
