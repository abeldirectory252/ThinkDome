"""Request logger service using SQLite to inspect and log all sandbox operations."""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, List, Dict, Optional
from thinkdome.core.config import Settings, get_settings
from thinkdome.platform.database.service import DatabaseService

logger = logging.getLogger(__name__)
_SENSITIVE_LOG_KEYS = ("password", "secret", "token", "api_key", "authorization", "credential", "private_key")


def _safe_log_payload(value: Any, key: str = "", max_bytes: int = 262_144) -> Any:
    """Redact sensitive fields and bound persisted request/response payloads."""
    key_normalized = key.lower().replace("-", "_")
    if any(part in key_normalized for part in _SENSITIVE_LOG_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        value = {str(k): _safe_log_payload(v, str(k), max_bytes) for k, v in value.items()}
    elif isinstance(value, list):
        value = [_safe_log_payload(v, max_bytes=max_bytes) for v in value[:1000]]
    elif not isinstance(value, (str, int, float, bool)) and value is not None:
        value = f"<{type(value).__name__}>"
    if isinstance(value, str) and len(value.encode("utf-8")) > max_bytes:
        value = value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore") + "...[truncated]"
    return value


def _serialize_log_payload(value: Any) -> str:
    max_bytes = get_settings().REQUEST_LOG_MAX_PAYLOAD_BYTES
    safe = _safe_log_payload(value, max_bytes=max_bytes)
    encoded = json.dumps(safe, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > max_bytes:
        encoded = encoded.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore") + "...[truncated]"
    return encoded

class RequestLogService:
    """Inspects and persists orchestrator execution logs in SQLite database."""

    def __init__(self, settings: Settings, db_service: DatabaseService) -> None:
        self.settings = settings
        self.db_service = db_service
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        
        # Max logs limit to keep database query latency low
        self.max_logs = 1000
        
        # Migrate old JSON request logs to DB
        self._migrate_json_logs()

    def _migrate_json_logs(self) -> None:
        """Migrate existing JSON logs into SQLite database."""
        logs_file = self.storage_dir / "request_logs.json"
        if logs_file.exists():
            try:
                logs_data = json.loads(logs_file.read_text(encoding="utf-8"))
                for log in reversed(logs_data): # Insert oldest first to maintain ordering
                    # Check if already exists in DB
                    exists = self.db_service.fetch_one(
                        "SELECT 1 FROM request_logs WHERE request_id = ? AND timestamp = ?",
                        (log.get("request_id", ""), log.get("timestamp", ""))
                    )
                    if not exists:
                        self.db_service.execute(
                            """
                            INSERT INTO request_logs (
                                request_id, timestamp, display_name, role, client_ip, 
                                tool_name, request_payload, response_payload, status, duration_ms
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                log.get("request_id", "unknown"),
                                log.get("timestamp", datetime.utcnow().isoformat()),
                                log.get("display_name", "Anonymous"),
                                log.get("role", "LLM"),
                                log.get("client_ip", "127.0.0.1"),
                                log.get("tool_name", "unknown"),
                                json.dumps(log.get("request_payload", {})),
                                json.dumps(log.get("response_payload", "")),
                                log.get("status", "success"),
                                log.get("duration_ms", 0.0)
                            )
                        )
                logger.info("Migrated old request logs from JSON to SQLite database.")
                logs_file.rename(logs_file.with_suffix(".json.migrated"))
            except Exception as e:
                logger.error(f"Failed to migrate request_logs.json: {e}")

    def log_request(
        self,
        client_ip: str,
        user_info: dict,
        tool_use: dict,
        tool_result: dict,
        duration_ms: float,
        sandbox_id: Optional[str] = None
    ) -> None:
        """Record an execution request and persist it into the database."""
        try:
            request_id = tool_use.get("id", "unknown")
            timestamp = datetime.utcnow().isoformat()
            display_name = user_info.get("display_name", "Anonymous")
            role = user_info.get("role", "LLM")
            tool_name = tool_use.get("name", "unknown")
            request_payload = _serialize_log_payload(tool_use.get("input", {}))
            
            # response payload can be string or dict
            resp_content = tool_result.get("content", "")
            if isinstance(resp_content, (dict, list)):
                response_payload = _serialize_log_payload(resp_content)
            else:
                response_payload = _serialize_log_payload(str(resp_content))
                
            status = "error" if tool_result.get("is_error", False) else "success"
            duration = round(duration_ms, 2)

            self.db_service.execute(
                """
                INSERT INTO request_logs (
                    request_id, timestamp, display_name, role, client_ip, 
                    tool_name, request_payload, response_payload, status, duration_ms, sandbox_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id, timestamp, display_name, role, client_ip,
                    tool_name, request_payload, response_payload, status, duration, sandbox_id
                )
            )
            
            # Prune old logs to avoid database bloat
            self._prune_old_logs()
        except Exception as e:
            logger.error(f"Failed to log request in database: {e}")

    def _prune_old_logs(self) -> None:
        """Limit the request logs size to max_logs."""
        try:
            row = self.db_service.fetch_one("SELECT COUNT(*) as count FROM request_logs")
            if row and row["count"] > self.max_logs:
                # Find the boundary ID
                offset = row["count"] - self.max_logs
                boundary_row = self.db_service.fetch_one(
                    f"SELECT id FROM request_logs ORDER BY id ASC LIMIT 1 OFFSET {offset}"
                )
                if boundary_row:
                    self.db_service.execute(
                        "DELETE FROM request_logs WHERE id < ?", (boundary_row["id"],)
                    )
        except Exception as e:
            logger.error(f"Failed to prune old request logs: {e}")

    def get_logs(self, limit: int = 100, actor: Optional[str] = None) -> list[dict[str, Any]]:
        """Get the latest request logs from database."""
        try:
            from thinkdome.platform.observability.models import RequestLog
            query = RequestLog.query()
            if actor:
                query = query.filter(display_name=actor)
            rows = query.all()
            rows.sort(key=lambda row: row.id, reverse=True)
            return [self._decode_log(row.to_dict()) for row in rows[:limit]]
        except Exception as e:
            logger.error(f"Failed to fetch request logs from database: {e}")
            return []

    @staticmethod
    def _decode_log(log_entry: dict[str, Any]) -> dict[str, Any]:
        for field in ("request_payload", "response_payload"):
            try:
                log_entry[field] = json.loads(log_entry[field])
            except (TypeError, json.JSONDecodeError, KeyError):
                pass
        return log_entry

    def get_audit_events(
        self,
        limit: int = 100,
        actor: Optional[str] = None,
        execution_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Read legacy audit events through the ORM."""
        from thinkdome.platform.observability.models import LegacyAuditLog
        query = LegacyAuditLog.query()
        if actor:
            query = query.filter(actor=actor)
        rows = [row.to_dict() for row in query.all()]
        if execution_only:
            rows = [row for row in rows if row.get("action") in {"mcp_call_tool", "sandbox_execution_intent"}]
        rows.sort(key=lambda row: row.get("id", 0), reverse=True)
        return rows[:limit]

    def get_audit_event(self, audit_id: str) -> Optional[dict[str, Any]]:
        """Read one legacy audit event through the ORM."""
        from thinkdome.platform.observability.models import LegacyAuditLog
        row = LegacyAuditLog.get(audit_id)
        return row.to_dict() if row else None

    def find_related_log(self, timestamp: Any, window_seconds: float = 2.0) -> Optional[dict[str, Any]]:
        """Find the closest request log without database-specific date SQL."""
        if not timestamp:
            return None

        def parse(value: Any) -> Optional[datetime]:
            if isinstance(value, datetime):
                return value
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None

        target = parse(timestamp)
        if target is None:
            return None
        candidates = []
        from thinkdome.platform.observability.models import RequestLog
        for row in RequestLog.query().all():
            current = parse(row.timestamp)
            if current is not None:
                distance = abs((current - target).total_seconds())
                if distance < window_seconds:
                    candidates.append((distance, row))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return self._decode_log(candidates[0][1].to_dict())

    def clear_logs(self, actor: str = "admin", actor_ip: str = "unknown") -> None:
        """Clear all request logs and record the action in audit logs."""
        try:
            self.db_service.execute("DELETE FROM request_logs")
            self.db_service.log_audit(
                actor=actor,
                action="clear_logs",
                ip_address=actor_ip,
                details={}
            )
            logger.info("Request logs cleared by admin.")
        except Exception as e:
            logger.error(f"Failed to clear request logs: {e}")
