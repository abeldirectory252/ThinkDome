"""Segregation of Duties (SoD) audit tools.

Tools: audit_check_sod_conflicts
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditAssertion,
    Confidence,
    RiskRating,
    SoDConflict,
    audit_response,
)
from thinkdome.apps.erp.audit.config import get_sod_matrix

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def check_sod_conflicts(tool_input: Dict[str, Any]) -> str:
    """Analyze active users against the Segregation of Duties conflict matrix."""
    client = _get_client()
    sod_matrix = get_sod_matrix()

    try:
        # Get all active users
        users = await client.get_list(
            "User",
            filters={"enabled": 1},
            fields=["name", "email", "first_name", "last_name"],
            limit_page_length=500,
        )

        # Get role links
        role_links = await client.get_list(
            "Has Role",
            fields=["parent", "role"],
            limit_page_length=2000,
        )

        # Build user-to-roles mapping
        user_roles: Dict[str, List[str]] = {}
        for rl in role_links:
            usr = rl.get("parent")
            role = rl.get("role")
            if usr and role:
                if usr not in user_roles:
                    user_roles[usr] = []
                user_roles[usr].append(role)

        conflicts: List[SoDConflict] = []
        findings: List[AuditFinding] = []

        for user in users:
            u_email = user.get("email") or user.get("name")
            roles = user_roles.get(u_email, [])

            # Check conflicts against configuration
            for rule in sod_matrix:
                role_a = rule.get("role_a")
                role_b = rule.get("role_b")
                if role_a in roles and role_b in roles:
                    conflict_inst = SoDConflict(
                        user=u_email,
                        user_email=u_email,
                        role_a=role_a,
                        role_b=role_b,
                        conflict=rule.get("conflict", "Undefined conflict"),
                        risk=RiskRating(rule.get("risk", "HIGH")),
                    )
                    conflicts.append(conflict_inst)

                    findings.append(AuditFinding(
                        title=f"SoD Conflict: {u_email}",
                        risk_rating=conflict_inst.risk,
                        assertions=[AuditAssertion.PRESENTATION_AND_DISCLOSURE],
                        observation=f"User {u_email} possesses conflicting roles: {role_a} and {role_b}.",
                        audit_reasoning=f"This violates Segregation of Duties. Conflict: {conflict_inst.conflict}",
                        impact="User can perform end-to-end transactions (e.g. create and approve) bypassing standard authorization controls.",
                        recommendation=f"Revoke either {role_a} or {role_b} from {u_email}. Assign roles to separate employees.",
                        confidence=Confidence.HIGH,
                    ))

        return json.dumps(audit_response(
            data={"conflicts": [c.model_dump() for c in conflicts], "count": len(conflicts)},
            evidence_source="User / Has Role",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="User",
            confidence=Confidence.LOW, warnings=[f"SoD checks failed: {e}"],
        ))
