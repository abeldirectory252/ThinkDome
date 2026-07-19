"""Audit reporting and presentation tools.

Tools: audit_create_finding, audit_generate_audit_report,
       audit_generate_management_letter
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
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

# Thread-safe in-memory cache of findings generated during current run
_findings_cache: List[AuditFinding] = []


def clear_findings_cache() -> None:
    _findings_cache.clear()


async def create_finding(tool_input: Dict[str, Any]) -> str:
    """Create a formal audit finding with risk ratings, assertions, and recommendations."""
    try:
        assertions = [AuditAssertion(a) for a in tool_input.get("assertions", [])]
        finding = AuditFinding(
            title=tool_input["title"],
            risk_rating=RiskRating(tool_input["risk_rating"]),
            assertions=assertions,
            erpnext_documents=tool_input.get("erpnext_documents", []),
            observation=tool_input.get("observation", ""),
            audit_reasoning=tool_input.get("audit_reasoning", ""),
            impact=tool_input.get("impact", ""),
            recommendation=tool_input.get("recommendation", ""),
            confidence=Confidence(tool_input.get("confidence", "HIGH")),
            confidence_explanation=tool_input.get("confidence_explanation"),
        )

        _findings_cache.append(finding)

        return json.dumps(audit_response(
            data=finding.model_dump(),
            evidence_source="Audit Finding Engine",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Audit Finding Engine",
            confidence=Confidence.LOW, warnings=[f"Finding creation failed: {e}"],
        ))


async def generate_audit_report(tool_input: Dict[str, Any]) -> str:
    """Produce the final comprehensive audit report including executive summaries and findings."""
    company = tool_input.get("company", "All Companies")
    from_date = tool_input.get("from_date", "None")
    to_date = tool_input.get("to_date", "None")

    try:
        report = {
            "title": f"ERPNext External Financial Audit Report for {company}",
            "period": f"{from_date} to {to_date}",
            "executive_summary": (
                "Based on procedures performed, we have obtained reasonable assurance "
                "regarding the integrity of the financial records and controls. "
                f"We identified {len(_findings_cache)} finding(s) that require management attention."
            ),
            "overall_audit_conclusion": (
                "UNQUALIFIED AUDIT OPINION (Clean)" if not any(f.risk_rating == RiskRating.CRITICAL for f in _findings_cache)
                else "QUALIFIED AUDIT OPINION (Adverse findings detected)"
            ),
            "findings": [f.model_dump() for f in _findings_cache] if tool_input.get("include_findings", True) else [],
            "generated_at": datetime.utcnow().isoformat(),
        }

        return json.dumps(audit_response(
            data=report,
            evidence_source="Audit Report Engine",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Audit Report Engine",
            confidence=Confidence.LOW, warnings=[f"Report generation failed: {e}"],
        ))


async def generate_management_letter(tool_input: Dict[str, Any]) -> str:
    """Produce the management letter with control recommendations."""
    company = tool_input.get("company", "All Companies")

    try:
        # Group findings into weaknesses
        letter = {
            "title": f"Management Letter on Internal Control System for {company}",
            "summary": "This letter outlines significant deficiencies and internal control weaknesses found during our audit.",
            "weaknesses": [
                {
                    "title": f.title,
                    "severity": f.risk_rating.value,
                    "observation": f.observation,
                    "recommendation": f.recommendation,
                }
                for f in _findings_cache if f.risk_rating in (RiskRating.HIGH, RiskRating.CRITICAL)
            ],
            "conclusion": "We recommend that management addresses these items promptly to minimize transaction risks.",
            "generated_at": datetime.utcnow().isoformat(),
        }

        return json.dumps(audit_response(
            data=letter,
            evidence_source="Audit Report Engine",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Audit Report Engine",
            confidence=Confidence.LOW, warnings=[f"Failed to generate management letter: {e}"],
        ))
