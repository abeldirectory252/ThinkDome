"""Stateful session management for REPL-like execution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from thinkdome.core.config import Settings
from thinkdome.models.sessions import (
    CreateSessionRequest,
    SessionInfo,
    SessionExecRequest,
    SessionExecResponse,
)
from thinkdome.models.execution import ExecuteRequest
from thinkdome.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


class SessionService:
    """Manages stateful execution sessions."""

    def __init__(self, settings: Settings, execution_service: ExecutionService) -> None:
        self.settings = settings
        self.execution_service = execution_service
        self._sessions: dict[str, SessionInfo] = {}
        self._history: dict[str, list[str]] = {}  # session_id -> list of code blocks

    def create(self, request: CreateSessionRequest) -> SessionInfo:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        info = SessionInfo(
            session_id=session_id,
            language=request.language,
            status="active",
            created_at=now,
            last_activity=now,
        )
        self._sessions[session_id] = info
        self._history[session_id] = []
        logger.info(f"Session created: {session_id}")
        return info

    def get(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    async def execute_in_session(
        self, session_id: str, request: SessionExecRequest
    ) -> Optional[SessionExecResponse]:
        session = self._sessions.get(session_id)
        if not session or session.status != "active":
            return None

        # Accumulate history for REPL context
        self._history[session_id].append(request.code)
        full_code = "\n".join(self._history[session_id])

        exec_request = ExecuteRequest(
            code=full_code,
            language=session.language,
            timeout_ms=request.timeout_ms,
            last_line_interactive=request.last_line_interactive,
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

    def close(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.status = "closed"
        self._history.pop(session_id, None)
        return True

    async def cleanup_all(self) -> None:
        """Close all active sessions."""
        for sid in list(self._sessions.keys()):
            self.close(sid)
        logger.info("All sessions cleaned up")
