"""Sandbox diagnostics service — logs, inspection, events.

Provides per-sandbox diagnostic capabilities for debugging without SSH access.
Works with Docker, MicroVM, and subprocess backends.

Inspired by OpenSandbox's DevOps diagnostics API.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# Max events to retain per sandbox
MAX_EVENTS_PER_SANDBOX = 500


@dataclass
class SandboxEvent:
    """A lifecycle event for a sandbox."""
    timestamp: float
    event_type: str  # e.g. "created", "started", "paused", "resumed", "error", "exec"
    message: str
    details: Dict[str, str] = field(default_factory=dict)


class DiagnosticsService:
    """Collects and serves per-sandbox diagnostic information.

    Usage:
        diag = DiagnosticsService(docker_client=client)
        diag.record_event("sb_123", "created", "Sandbox created with python:3.12")
        logs = diag.get_logs("sb_123", tail=50)
        summary = diag.get_summary("sb_123")
    """

    def __init__(self, docker_client=None) -> None:
        self._docker_client = docker_client
        # Per-sandbox event log
        self._events: Dict[str, Deque[SandboxEvent]] = defaultdict(
            lambda: deque(maxlen=MAX_EVENTS_PER_SANDBOX)
        )

    def record_event(
        self,
        sandbox_id: str,
        event_type: str,
        message: str,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a lifecycle event for a sandbox."""
        event = SandboxEvent(
            timestamp=time.time(),
            event_type=event_type,
            message=message,
            details=details or {},
        )
        self._events[sandbox_id].append(event)

    def get_logs(
        self,
        sandbox_id: str,
        tail: int = 100,
        since: Optional[str] = None,
        container_name: Optional[str] = None,
    ) -> str:
        """Retrieve container logs for a sandbox.

        Args:
            sandbox_id: Target sandbox ID.
            tail: Number of trailing log lines.
            since: Only return logs newer than this duration (e.g. "10m", "1h").
            container_name: Optional container name for multi-container setups.

        Returns:
            Plain-text log output.
        """
        if self._docker_client:
            try:
                return self._docker_get_logs(sandbox_id, tail, since)
            except Exception as e:
                logger.warning(f"Failed to get Docker logs for {sandbox_id}: {e}")
                return f"[error] Failed to retrieve logs: {e}"

        # Fallback: return event log as text
        return self._events_as_text(sandbox_id, limit=tail)

    def get_inspect(self, sandbox_id: str) -> str:
        """Retrieve detailed inspection info for a sandbox container.

        Returns:
            Plain-text inspection output.
        """
        if self._docker_client:
            try:
                return self._docker_inspect(sandbox_id)
            except Exception as e:
                logger.warning(f"Failed to inspect {sandbox_id}: {e}")
                return f"[error] Failed to inspect sandbox: {e}"

        return f"[info] Inspection not available for sandbox {sandbox_id} (no Docker client)."

    def get_events(self, sandbox_id: str, limit: int = 50) -> str:
        """Retrieve lifecycle events for a sandbox as formatted text.

        Args:
            sandbox_id: Target sandbox ID.
            limit: Maximum number of events.

        Returns:
            Plain-text event output.
        """
        return self._events_as_text(sandbox_id, limit=limit)

    def get_events_list(self, sandbox_id: str, limit: int = 50) -> List[dict]:
        """Retrieve lifecycle events as a list of dicts (for JSON responses)."""
        events = list(self._events.get(sandbox_id, []))
        events = events[-limit:]
        return [
            {
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "message": e.message,
                "details": e.details,
            }
            for e in events
        ]

    def get_summary(
        self,
        sandbox_id: str,
        log_tail: int = 50,
        event_limit: int = 20,
    ) -> str:
        """One-shot diagnostics summary: inspect + events + logs.

        Returns:
            Combined plain-text diagnostic report.
        """
        sections: list[str] = []

        sections.append("=" * 72)
        sections.append("SANDBOX DIAGNOSTICS SUMMARY")
        sections.append(f"Sandbox ID: {sandbox_id}")
        sections.append("=" * 72)

        # Inspect
        sections.append("")
        sections.append("-" * 40)
        sections.append("INSPECT")
        sections.append("-" * 40)
        try:
            sections.append(self.get_inspect(sandbox_id))
        except Exception:
            logger.exception("Failed to collect inspect diagnostics for %s", sandbox_id)
            sections.append("[error] Failed to collect inspect diagnostics.")

        # Events
        sections.append("")
        sections.append("-" * 40)
        sections.append("EVENTS")
        sections.append("-" * 40)
        try:
            sections.append(self.get_events(sandbox_id, limit=event_limit))
        except Exception:
            logger.exception("Failed to collect event diagnostics for %s", sandbox_id)
            sections.append("[error] Failed to collect event diagnostics.")

        # Logs
        sections.append("")
        sections.append("-" * 40)
        sections.append(f"LOGS (last {log_tail} lines)")
        sections.append("-" * 40)
        try:
            sections.append(self.get_logs(sandbox_id, tail=log_tail))
        except Exception:
            logger.exception("Failed to collect log diagnostics for %s", sandbox_id)
            sections.append("[error] Failed to collect log diagnostics.")

        return "\n".join(sections) + "\n"

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        """Remove all diagnostic data for a sandbox."""
        self._events.pop(sandbox_id, None)

    # ── Docker helpers ──

    def _docker_get_logs(self, sandbox_id: str, tail: int, since: Optional[str]) -> str:
        """Get logs from Docker container."""
        # Try to find container by sandbox_id label or container name
        containers = self._docker_client.containers.list(
            all=True,
            filters={"label": f"thinkdome.sandbox_id={sandbox_id}"},
        )
        if not containers:
            # Fallback: try by name
            try:
                container = self._docker_client.containers.get(sandbox_id)
                containers = [container]
            except Exception:
                return f"[info] No container found for sandbox {sandbox_id}."

        container = containers[0]
        kwargs = {"tail": tail, "timestamps": True}
        if since:
            kwargs["since"] = since

        logs = container.logs(**kwargs)
        if isinstance(logs, bytes):
            return logs.decode("utf-8", errors="replace")
        return str(logs)

    def _docker_inspect(self, sandbox_id: str) -> str:
        """Inspect Docker container."""
        import json

        containers = self._docker_client.containers.list(
            all=True,
            filters={"label": f"thinkdome.sandbox_id={sandbox_id}"},
        )
        if not containers:
            try:
                container = self._docker_client.containers.get(sandbox_id)
                containers = [container]
            except Exception:
                return f"[info] No container found for sandbox {sandbox_id}."

        container = containers[0]
        attrs = container.attrs
        # Return a readable subset
        summary = {
            "Id": attrs.get("Id", "")[:12],
            "Name": attrs.get("Name", ""),
            "State": attrs.get("State", {}),
            "Image": attrs.get("Config", {}).get("Image", ""),
            "Created": attrs.get("Created", ""),
            "Platform": attrs.get("Platform", ""),
            "HostConfig": {
                "Memory": attrs.get("HostConfig", {}).get("Memory"),
                "NanoCpus": attrs.get("HostConfig", {}).get("NanoCpus"),
                "PidsLimit": attrs.get("HostConfig", {}).get("PidsLimit"),
                "NetworkMode": attrs.get("HostConfig", {}).get("NetworkMode"),
                "ReadonlyRootfs": attrs.get("HostConfig", {}).get("ReadonlyRootfs"),
            },
        }
        return json.dumps(summary, indent=2, default=str)

    # ── Internal helpers ──

    def _events_as_text(self, sandbox_id: str, limit: int = 50) -> str:
        """Format events as plain text."""
        from datetime import datetime, timezone

        events = list(self._events.get(sandbox_id, []))
        events = events[-limit:]

        if not events:
            return f"[info] No events recorded for sandbox {sandbox_id}."

        lines = []
        for e in events:
            ts = datetime.fromtimestamp(e.timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            details_str = f" ({', '.join(f'{k}={v}' for k, v in e.details.items())})" if e.details else ""
            lines.append(f"[{ts}] {e.event_type}: {e.message}{details_str}")
        return "\n".join(lines)
