"""Append-only JSONL audit logging for Filebox mutations.

Every file create/update/delete/move is logged to a date-partitioned
JSONL file under ``logs/YYYY/MM/DD/``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thinkdome.filebox.schemas import AuditEvent

logger = logging.getLogger(__name__)


class AuditLogger:
    """Structured audit log writer/reader for a single Filebox root."""

    def __init__(self, filebox_root: Path):
        self._root = filebox_root
        self._logs_dir = filebox_root / "logs"

    # ── Writing ──────────────────────────────────────────────────────────

    def log(
        self,
        action: str,
        path: str,
        *,
        actor: str = "agent",
        reason: str = "",
        result: str = "ok",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append one audit event to today's log file."""
        now = datetime.now(timezone.utc)
        event = AuditEvent(
            timestamp=now.isoformat(),
            action=action,
            path=path,
            actor=actor,
            reason=reason,
            result=result,
            details=details or {},
        )
        log_dir = self._logs_dir / now.strftime("%Y/%m/%d")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "audit.jsonl"
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        except Exception:
            logger.exception("Failed to write audit event: %s %s", action, path)
        return event

    # ── Reading ──────────────────────────────────────────────────────────

    def get_log(
        self,
        date: datetime | None = None,
        *,
        limit: int = 500,
    ) -> list[AuditEvent]:
        """Read audit events for a given date (default: today)."""
        target = date or datetime.now(timezone.utc)
        log_file = (
            self._logs_dir
            / target.strftime("%Y/%m/%d")
            / "audit.jsonl"
        )
        if not log_file.exists():
            return []
        events: list[AuditEvent] = []
        try:
            for line in log_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                events.append(AuditEvent(**json.loads(line)))
                if len(events) >= limit:
                    break
        except Exception:
            logger.exception("Failed to read audit log: %s", log_file)
        return events

    def recent(self, limit: int = 50) -> list[AuditEvent]:
        """Return the most recent audit events across all dates."""
        events: list[AuditEvent] = []
        if not self._logs_dir.exists():
            return events
        # Walk year/month/day directories in reverse order.
        for day_dir in sorted(self._logs_dir.rglob("audit.jsonl"), reverse=True):
            try:
                lines = day_dir.read_text(encoding="utf-8").splitlines()
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    events.append(AuditEvent(**json.loads(line)))
                    if len(events) >= limit:
                        return events
            except Exception:
                continue
        return events
