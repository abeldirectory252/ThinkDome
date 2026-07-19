"""User access and role configuration audit tools.

Tools: audit_get_users, audit_get_roles, audit_get_permissions,
       audit_get_system_managers, audit_permission_changes,
       audit_login_history, audit_failed_login_attempts
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditAssertion,
    Confidence,
    RiskRating,
    audit_response,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_users(tool_input: Dict[str, Any]) -> str:
    """Fetch active users, email addresses, enabled/disabled status, and last login dates."""
    client = _get_client()
    enabled = tool_input.get("enabled")

    try:
        filters: Dict[str, Any] = {}
        if enabled is not None:
            filters["enabled"] = 1 if enabled else 0

        users = await client.get_list(
            "User",
            filters=filters,
            fields=["name", "email", "first_name", "last_name", "enabled", "last_login", "creation", "owner"],
            order_by="last_login desc",
            limit_page_length=tool_input.get("limit", 500),
        )

        return json.dumps(audit_response(
            data={"users": users, "count": len(users)},
            evidence_source="User",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="User",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch users: {e}"],
        ))


async def get_roles(tool_input: Dict[str, Any]) -> str:
    """Fetch all defined security roles and basic settings."""
    client = _get_client()

    try:
        roles = await client.get_list(
            "Role",
            filters={"disabled": 0},
            fields=["name", "two_factor_auth", "desk_access", "creation"],
            limit_page_length=200,
        )

        return json.dumps(audit_response(
            data={"roles": roles, "count": len(roles)},
            evidence_source="Role",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Role",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch roles: {e}"],
        ))


async def get_permissions(tool_input: Dict[str, Any]) -> str:
    """Fetch permission rules configuration mapping roles to doctype access rights."""
    client = _get_client()

    try:
        # Custom DocPerm contains permissions in Frappe
        permissions = await client.get_list(
            "Custom DocPerm",
            fields=["name", "parent", "role", "permlevel", "read", "write", "create", "delete", "submit", "cancel", "amend"],
            limit_page_length=500,
        )

        return json.dumps(audit_response(
            data={"permissions": permissions, "count": len(permissions)},
            evidence_source="Custom DocPerm",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Custom DocPerm",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch permission rules: {e}"],
        ))


async def get_system_managers(tool_input: Dict[str, Any]) -> str:
    """Identify users with superuser / System Manager privileges."""
    client = _get_client()

    try:
        # In Frappe, user roles are stored in User Role link table
        user_roles = await client.get_list(
            "Has Role",
            filters={"role": "System Manager"},
            fields=["parent", "role"],
            limit_page_length=100,
        )

        managers = [ur.get("parent") for ur in user_roles if ur.get("parent")]

        # Get full user profiles for the managers to see enabled status
        details = []
        for m in managers:
            try:
                ud = await client.get_doc("User", m)
                details.append({
                    "email": ud.get("email"),
                    "name": f"{ud.get('first_name', '')} {ud.get('last_name', '')}".strip(),
                    "enabled": ud.get("enabled"),
                    "last_login": ud.get("last_login"),
                })
            except Exception:
                details.append({"email": m, "error": "Could not retrieve user document"})

        findings = []
        active_managers = [m for m in details if m.get("enabled")]
        if len(active_managers) > 5:
            findings.append(AuditFinding(
                title="Excessive Active System Managers",
                risk_rating=RiskRating.HIGH if len(active_managers) > 10 else RiskRating.MEDIUM,
                assertions=[AuditAssertion.PRESENTATION_AND_DISCLOSURE],
                observation=f"There are {len(active_managers)} active users with System Manager roles.",
                audit_reasoning="A high number of administrators increases the risk of unauthorized system configuration changes, logs deletion, or privilege abuse.",
                recommendation="Review system manager listings and revoke privileges from users who do not require them for core administration.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"system_managers": details, "count": len(details)},
            evidence_source="Has Role / User",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Has Role",
            confidence=Confidence.LOW, warnings=[f"Failed to analyze System Managers: {e}"],
        ))


async def permission_changes(tool_input: Dict[str, Any]) -> str:
    """Audit version logs and logs of changes made to user permissions/roles."""
    client = _get_client()

    try:
        # In Frappe, look at Version log on User or Role / Custom DocPerm doctypes
        versions = await client.get_list(
            "Version",
            filters={"ref_doctype": ["in", ["User", "Custom DocPerm", "Role"]]},
            fields=["name", "ref_doctype", "ref_name", "owner", "creation", "data"],
            order_by="creation desc",
            limit_page_length=200,
        )

        return json.dumps(audit_response(
            data={"permission_changes": versions, "count": len(versions)},
            evidence_source="Version",
            confidence=Confidence.HIGH,
            warnings=["Please review authorization approvals for these changes."] if versions else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Version",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch permission changes: {e}"],
        ))


async def login_history(tool_input: Dict[str, Any]) -> str:
    """Fetch user login/logout histories."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("user"):
            filters["user"] = tool_input["user"]
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]

        history = await client.get_list(
            "Activity Log",
            filters={"operation": "Login", **filters},
            fields=["name", "user", "creation", "status", "ip_address", "user_agent"],
            order_by="creation desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        return json.dumps(audit_response(
            data={"login_history": history, "count": len(history)},
            evidence_source="Activity Log",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Activity Log",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch login history: {e}"],
        ))


async def failed_login_attempts(tool_input: Dict[str, Any]) -> str:
    """Find failed login attempts to check brute-force or unauthorized access indicators."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"operation": "Login", "status": "Failed"}
        if tool_input.get("user"):
            filters["user"] = tool_input["user"]
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]

        failed = await client.get_list(
            "Activity Log",
            filters=filters,
            fields=["name", "user", "creation", "status", "ip_address", "user_agent"],
            order_by="creation desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        findings = []
        if len(failed) > 20:
            findings.append(AuditFinding(
                title="Elevated Failed Login Attempts",
                risk_rating=RiskRating.HIGH if len(failed) > 100 else RiskRating.MEDIUM,
                assertions=[AuditAssertion.PRESENTATION_AND_DISCLOSURE],
                observation=f"Detected {len(failed)} failed login attempts in the audit log window.",
                audit_reasoning="High counts of failed logins indicates potential brute force attempts or user account compromise attempts.",
                recommendation="Investigate the source IP addresses of the failed login entries. Enable multi-factor authentication if disabled.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"failed_logins": failed, "count": len(failed)},
            evidence_source="Activity Log",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Activity Log",
            confidence=Confidence.LOW, warnings=[f"Failed to check failed logins: {e}"],
        ))
