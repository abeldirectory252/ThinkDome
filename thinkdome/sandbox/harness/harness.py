"""Trusted harness control plane — separates coordination from compute execution (OpenAI pattern)."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    """Immutable entry in the Harness audit trail."""
    record_id: str
    timestamp: float = field(default_factory=time.time)
    action: str = ""
    actor: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    approved_by: Optional[str] = None


class ApprovalPipeline:
    """Manages human-in-the-loop approvals for sensitive sandbox operations."""

    def __init__(self) -> None:
        self._rules: Dict[str, Callable[[str, dict], bool]] = {}
        self._pending_approvals: Dict[str, dict] = {}
        self._approval_counter = 0

    def register_approval_rule(self, tool_name: str, rule_fn: Callable[[str, dict], bool]) -> None:
        """Register a callback to evaluate if an action requires approval."""
        self._rules[tool_name] = rule_fn

    def requires_approval(self, tool_name: str, tool_input: dict, caller: str) -> bool:
        """Check if a tool call matches any registered approval rules."""
        if tool_name in self._rules:
            return self._rules[tool_name](caller, tool_input)
        return False

    def request_approval(self, tool_name: str, tool_input: dict, caller: str) -> str:
        """Stage an approval request and return a request ID."""
        self._approval_counter += 1
        req_id = f"appr_{self._approval_counter:04d}"
        self._pending_approvals[req_id] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "caller": caller,
            "status": "pending",
            "timestamp": time.time()
        }
        return req_id

    def approve(self, req_id: str, approver: str) -> bool:
        """Approve a pending request."""
        if req_id in self._pending_approvals and self._pending_approvals[req_id]["status"] == "pending":
            self._pending_approvals[req_id]["status"] = "approved"
            self._pending_approvals[req_id]["approver"] = approver
            return True
        return False

    def reject(self, req_id: str, rejector: str) -> bool:
        """Reject a pending request."""
        if req_id in self._pending_approvals and self._pending_approvals[req_id]["status"] == "pending":
            self._pending_approvals[req_id]["status"] = "rejected"
            self._pending_approvals[req_id]["rejector"] = rejector
            return True
        return False

    def get_request(self, req_id: str) -> Optional[dict]:
        """Fetch request details."""
        return self._pending_approvals.get(req_id)


class Harness:
    """Trusted control plane separating model orchestration from containerized sandboxes.

    Responsibilities:
      - Coordinate agent execution steps
      - Hold secrets/credentials securely (Vault integration)
      - Register and map native sandbox Capabilities
      - Intercept and audit all tool calls with human approvals
      - Log execution traces to append-only audit files
    """

    def __init__(self, settings, db_service) -> None:
        self.settings = settings
        self.db_service = db_service
        self.approvals = ApprovalPipeline()
        
        # In-memory audit trail (backed by DB log_audit)
        self._audit_trail: List[AuditRecord] = []

    def log_event(self, action: str, actor: str, details: Dict[str, Any], approved_by: Optional[str] = None) -> None:
        """Write an append-only audit event log to DB and memory."""
        record_id = f"aud_{int(time.time() * 1000)}"
        record = AuditRecord(
            record_id=record_id,
            action=action,
            actor=actor,
            details=details,
            approved_by=approved_by
        )
        self._audit_trail.append(record)
        
        # Write to persistent audit log
        try:
            self.db_service.log_audit(
                actor=actor,
                action=action,
                details=details,
                ip_address="harness-internal"
            )
        except Exception as e:
            logger.error(f"Failed to log Harness audit event: {e}")

    async def execute_agent_step(
        self,
        tool_name: str,
        tool_input: dict,
        caller_identity: dict,
        sandbox_executor_fn: Callable[[str, dict], Any]
    ) -> dict:
        """Safely execute an agent loop step, managing approvals, audit logging and compute routing."""
        caller_name = caller_identity.get("username", "anonymous")
        
        # 1. Approval Check
        if self.approvals.requires_approval(tool_name, tool_input, caller_name):
            req_id = self.approvals.request_approval(tool_name, tool_input, caller_name)
            self.log_event(
                action="approval_requested",
                actor=caller_name,
                details={"tool_name": tool_name, "approval_req_id": req_id, "input": tool_input}
            )
            return {
                "type": "approval_required",
                "approval_req_id": req_id,
                "message": f"Execution of tool '{tool_name}' requires human approval."
            }

        # 2. Execution Routing
        self.log_event(
            action="tool_execution_start",
            actor=caller_name,
            details={"tool_name": tool_name, "input": tool_input}
        )
        
        start_time = time.monotonic()
        try:
            result = await sandbox_executor_fn(tool_name, tool_input)
            duration_ms = (time.monotonic() - start_time) * 1000.0
            
            # 3. Log results
            self.log_event(
                action="tool_execution_success",
                actor=caller_name,
                details={"tool_name": tool_name, "duration_ms": duration_ms}
            )
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000.0
            self.log_event(
                action="tool_execution_failure",
                actor=caller_name,
                details={"tool_name": tool_name, "error": str(e), "duration_ms": duration_ms}
            )
            return {
                "type": "tool_result",
                "content": f"Harness execution error: {str(e)}",
                "is_error": True
            }

    def get_audit_trail(self, limit: int = 100) -> List[dict]:
        """Retrieve recent harness records."""
        return [
            {
                "record_id": r.record_id,
                "timestamp": r.timestamp,
                "action": r.action,
                "actor": r.actor,
                "details": r.details,
                "approved_by": r.approved_by
            }
            for r in self._audit_trail[-limit:]
        ]
