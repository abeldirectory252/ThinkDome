"""Internal Controls testing tools.

Tools: audit_test_control
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditAssertion,
    ControlTestResult,
    ControlEffectiveness,
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


async def test_control(tool_input: Dict[str, Any]) -> str:
    """Test the effectiveness of a configured internal control (e.g. Purchase approval workflow)."""
    client = _get_client()
    control_name = tool_input["control_name"]

    result = ControlTestResult(
        control=control_name,
        description=f"Automated test for ERPNext internal control: {control_name}",
    )

    try:
        if control_name == "purchase_approval_workflow":
            # Test if purchase orders exceed a threshold or check if workflows exist and are obeyed
            workflows = await client.get_list("Workflow", filters={"document_type": "Purchase Order", "is_active": 1})
            if not workflows:
                result.design_effectiveness = ControlEffectiveness.INEFFECTIVE
                result.operating_effectiveness = ControlEffectiveness.INEFFECTIVE
                result.conclusion = "No active Workflow configuration found for Purchase Orders."
            else:
                result.design_effectiveness = ControlEffectiveness.EFFECTIVE
                # Test operating effectiveness: retrieve PO list and check if any bypassed workflow
                pos = await client.get_list("Purchase Order", filters={"docstatus": 1}, limit_page_length=50)
                result.sample_size = len(pos)

                exceptions = []
                for po in pos:
                    actions = await client.get_list(
                        "Workflow Action",
                        filters={"reference_doctype": "Purchase Order", "reference_name": po["name"]}
                    )
                    if not actions:
                        exceptions.append({"purchase_order": po["name"], "error": "Bypassed workflow actions"})

                result.exceptions = exceptions
                result.exception_count = len(exceptions)
                if exceptions:
                    result.operating_effectiveness = ControlEffectiveness.INEFFECTIVE
                    result.conclusion = f"Bypass exceptions found in {len(exceptions)} Purchase Orders."
                else:
                    result.operating_effectiveness = ControlEffectiveness.EFFECTIVE
                    result.conclusion = "All sampled Purchase Orders conformed to approval workflow states."

        elif control_name == "three_way_matching":
            # Test three way matching failures by delegating to purchase matching check
            from thinkdome.apps.erp.audit.purchase import test_three_way_matching
            match_str = await test_three_way_matching({
                "company": tool_input.get("company"),
                "from_date": tool_input.get("from_date"),
                "to_date": tool_input.get("to_date"),
                "limit": tool_input.get("sample_size", 25),
            })
            match_data = json.loads(match_str)
            inner_data = match_data.get("data", {})

            result.sample_size = inner_data.get("total_items", 0)
            result.exception_count = inner_data.get("failed_items", 0)

            if result.sample_size > 0:
                result.design_effectiveness = ControlEffectiveness.EFFECTIVE
                if result.exception_count > 0:
                    result.operating_effectiveness = ControlEffectiveness.INEFFECTIVE
                    result.conclusion = f"Exceptions found: {result.exception_count} items failed invoice-receipt-PO match."
                else:
                    result.operating_effectiveness = ControlEffectiveness.EFFECTIVE
                    result.conclusion = "All matching items conformed."
            else:
                result.design_effectiveness = ControlEffectiveness.UNABLE_TO_CONCLUDE
                result.conclusion = "No active purchase items found in test window."

        else:
            return json.dumps(audit_response(
                data=None, evidence_source="Control Manager",
                confidence=Confidence.LOW,
                warnings=[f"Unknown control name '{control_name}'. Available controls: purchase_approval_workflow, three_way_matching."],
            ))

        findings = []
        if result.operating_effectiveness == ControlEffectiveness.INEFFECTIVE:
            findings.append(AuditFinding(
                title=f"Internal Control Failure: {control_name}",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.ACCURACY],
                observation=result.conclusion,
                audit_reasoning=f"Internal control '{control_name}' failed effectiveness testing criteria.",
                recommendation=f"Address exceptions immediately. Re-enforce workflow limits or validation rules.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data=result.model_dump(),
            evidence_source="Workflow / Purchase Order / Purchase Invoice",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Control Manager",
            confidence=Confidence.LOW, warnings=[f"Control test failed: {e}"],
        ))
