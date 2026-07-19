"""Workflow audit tools.

Tools: audit_get_workflows, audit_workflow_history,
       audit_find_skipped_approvals, audit_find_approval_bypass
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
    audit_response,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_workflows(tool_input: Dict[str, Any]) -> str:
    """Fetch all defined approval workflow configurations and transitions."""
    client = _get_client()
    doctype = tool_input.get("doctype")

    try:
        filters: Dict[str, Any] = {"is_active": 1}
        if doctype:
            filters["document_type"] = doctype

        workflows = await client.get_list(
            "Workflow",
            filters=filters,
            fields=["name", "document_type", "is_active", "creation", "owner"],
            limit_page_length=100,
        )

        details = []
        for wf in workflows:
            try:
                # Retrieve workflow transitions and states
                full_wf = await client.get_doc("Workflow", wf["name"])
                details.append({
                    "name": wf["name"],
                    "document_type": wf["document_type"],
                    "states": full_wf.get("states", []),
                    "transitions": full_wf.get("transitions", []),
                })
            except Exception:
                details.append({
                    "name": wf["name"],
                    "document_type": wf["document_type"],
                    "error": "Could not retrieve details",
                })

        return json.dumps(audit_response(
            data={"workflows": details, "count": len(details)},
            evidence_source="Workflow",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch workflows: {e}"],
        ))


async def workflow_history(tool_input: Dict[str, Any]) -> str:
    """Fetch workflow log / transition history for a specific document."""
    client = _get_client()
    doctype = tool_input.get("doctype")
    docname = tool_input.get("document_name")

    if not doctype or not docname:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=["doctype and document_name are required"],
        ))

    try:
        actions = await client.get_list(
            "Workflow Action",
            filters={"reference_doctype": doctype, "reference_name": docname},
            fields=["name", "workflow_state", "status", "user", "creation", "completed_by"],
            order_by="creation asc",
            limit_page_length=100,
        )

        return json.dumps(audit_response(
            data={"workflow_actions": actions, "count": len(actions)},
            evidence_source="Workflow Action",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch workflow history: {e}"],
        ))


async def find_skipped_approvals(tool_input: Dict[str, Any]) -> str:
    """Find documents that skipped defined workflow transitions."""
    client = _get_client()
    doctype = tool_input.get("doctype")

    if not doctype:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=["doctype is required to check skipped approvals"],
        ))

    try:
        # Check active workflows for this doctype
        workflows = await client.get_list(
            "Workflow",
            filters={"document_type": doctype, "is_active": 1},
            fields=["name"],
            limit_page_length=5,
        )

        if not workflows:
            return json.dumps(audit_response(
                data={"skipped_documents": [], "count": 0},
                evidence_source="Workflow",
                confidence=Confidence.HIGH,
                warnings=[f"No active workflow defined for doctype '{doctype}'."],
            ))

        # Get submitted documents of this type
        docs = await client.get_list(
            doctype,
            filters={"docstatus": 1},
            fields=["name", "workflow_state", "creation", "owner"],
            limit_page_length=100,
        )

        skipped = []
        for d in docs:
            # Look for workflow actions
            actions = await client.get_list(
                "Workflow Action",
                filters={"reference_doctype": doctype, "reference_name": d["name"]},
                fields=["name"],
            )
            # If submitted but no workflow actions exist, it bypassed workflow states
            if not actions:
                skipped.append(d)

        findings = []
        if skipped:
            findings.append(AuditFinding(
                title=f"Workflow Bypass Detected on {doctype}",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.PRESENTATION_AND_DISCLOSURE],
                observation=f"{len(skipped)} submitted {doctype} documents bypassed the active workflow approval process.",
                audit_reasoning="Documents that bypass active workflows violate company internal controls and authorization policies.",
                recommendation="Investigate why these documents were directly submitted. Re-verify the transaction details.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"skipped_documents": skipped, "count": len(skipped)},
            evidence_source="Workflow Action / " + doctype,
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=[f"Workflow bypass check failed: {e}"],
        ))


async def find_approval_bypass(tool_input: Dict[str, Any]) -> str:
    """Find documents approved or submitted by users other than the designated workflow steps or roles."""
    client = _get_client()
    doctype = tool_input.get("doctype")

    if not doctype:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=["doctype is required"],
        ))

    try:
        workflows = await client.get_list(
            "Workflow",
            filters={"document_type": doctype, "is_active": 1},
            fields=["name"],
            limit_page_length=5,
        )

        if not workflows:
            return json.dumps(audit_response(
                data={"bypass_attempts": [], "count": 0},
                evidence_source="Workflow",
                confidence=Confidence.HIGH,
                warnings=[f"No active workflow found for doctype '{doctype}'."],
            ))

        # Retrieve transition rules to find approved statuses
        wf_doc = await client.get_doc("Workflow", workflows[0]["name"])
        transitions = wf_doc.get("transitions", [])

        # Fetch submitted documents
        docs = await client.get_list(
            doctype,
            filters={"docstatus": 1},
            fields=["name", "workflow_state", "owner", "modified_by", "creation"],
            limit_page_length=100,
        )

        bypass_list = []
        for d in docs:
            # Check the actual submitter/modifier
            actions = await client.get_list(
                "Workflow Action",
                filters={"reference_doctype": doctype, "reference_name": d["name"], "status": "Completed"},
                fields=["completed_by", "workflow_state"],
            )

            # If the modifier is not matching the workflow actions completer
            if actions:
                last_completed = actions[-1].get("completed_by")
                last_modifier = d.get("modified_by")
                if last_completed and last_modifier and last_completed != last_modifier:
                    # Let's check if the modifier is an Admin
                    bypass_list.append({
                        "document": d["name"],
                        "last_workflow_completer": last_completed,
                        "actual_submitting_user": last_modifier,
                        "workflow_state": d.get("workflow_state"),
                    })

        findings = []
        if bypass_list:
            findings.append(AuditFinding(
                title=f"Workflow Final Approval Bypassed on {doctype}",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE],
                observation=f"{len(bypass_list)} documents of type {doctype} were finalized/submitted by users other than the workflow process completer.",
                audit_reasoning="Direct DB modification or submission overrides skip segregation rules and bypass internal checks.",
                recommendation="Examine if Administrator or System Manager roles are overriding approval transitions.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"bypass_attempts": bypass_list, "count": len(bypass_list)},
            evidence_source="Workflow Action",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Workflow Action",
            confidence=Confidence.LOW, warnings=[f"Failed to check approval bypass: {e}"],
        ))
