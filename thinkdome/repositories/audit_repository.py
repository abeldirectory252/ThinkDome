"""Audit, Login History, and Session Repository using ThinkDome ORM."""

from __future__ import annotations

import json
from typing import Optional, List, Dict, Any
from thinkdome.repositories.base_repository import BaseRepository
from thinkdome.models.rbac_models import (
    RbacAuditLog,
    LoginHistory,
    RefreshToken,
    Session,
)


class AuditRepository(BaseRepository[RbacAuditLog]):
    """Repository handling audit trails, login histories, and session records."""

    def __init__(self) -> None:
        super().__init__(RbacAuditLog)

    def log_event(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "127.0.0.1",
    ) -> RbacAuditLog:
        """Create and persist an audit log entry."""
        log_entry = RbacAuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id or "",
            details=json.dumps(details or {}),
            ip_address=ip_address,
        )
        log_entry.save()
        return log_entry

    def record_login(
        self,
        user_id: str,
        status: str = "success",
        ip_address: str = "127.0.0.1",
        user_agent: str = "",
    ) -> LoginHistory:
        """Record user authentication login event."""
        history = LoginHistory(
            user_id=user_id,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        history.save()
        return history

    def create_session(
        self,
        user_id: str,
        session_token: str,
        expires_at: str,
        ip_address: str = "127.0.0.1",
        device_info: str = "",
    ) -> Session:
        """Create active session record."""
        session = Session(
            user_id=user_id,
            session_token=session_token,
            expires_at=expires_at,
            ip_address=ip_address,
            device_info=device_info,
        )
        session.save()
        return session

    def get_session(self, session_token: str) -> Optional[Session]:
        """Fetch active session by session token."""
        return Session.query().filter(session_token=session_token).first()

    def revoke_session(self, session_token: str) -> bool:
        """Revoke active session record."""
        session = self.get_session(session_token)
        if session:
            session.delete(soft=False)
            return True
        return False
