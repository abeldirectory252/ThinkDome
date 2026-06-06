"""Request logger service using SQLite to inspect and log all sandbox operations."""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, List, Dict
from thinkdome.core.config import Settings
from thinkdome.services.db_service import DatabaseService

logger = logging.getLogger(__name__)

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
        duration_ms: float
    ) -> None:
        """Record an execution request and persist it into the database."""
        try:
            request_id = tool_use.get("id", "unknown")
            timestamp = datetime.utcnow().isoformat()
            display_name = user_info.get("display_name", "Anonymous")
            role = user_info.get("role", "LLM")
            tool_name = tool_use.get("name", "unknown")
            request_payload = json.dumps(tool_use.get("input", {}))
            
            # response payload can be string or dict
            resp_content = tool_result.get("content", "")
            if isinstance(resp_content, (dict, list)):
                response_payload = json.dumps(resp_content)
            else:
                response_payload = str(resp_content)
                
            status = "error" if tool_result.get("is_error", False) else "success"
            duration = round(duration_ms, 2)

            self.db_service.execute(
                """
                INSERT INTO request_logs (
                    request_id, timestamp, display_name, role, client_ip, 
                    tool_name, request_payload, response_payload, status, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id, timestamp, display_name, role, client_ip,
                    tool_name, request_payload, response_payload, status, duration
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

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get the latest request logs from database."""
        try:
            rows = self.db_service.fetch_all(
                "SELECT * FROM request_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            logs = []
            for row in rows:
                log_entry = dict(row)
                # Parse JSON fields back
                try:
                    log_entry["request_payload"] = json.loads(log_entry["request_payload"])
                except Exception:
                    pass
                
                try:
                    # check if response payload is JSON dict
                    log_entry["response_payload"] = json.loads(log_entry["response_payload"])
                except Exception:
                    pass
                logs.append(log_entry)
            return logs
        except Exception as e:
            logger.error(f"Failed to fetch request logs from database: {e}")
            return []

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

