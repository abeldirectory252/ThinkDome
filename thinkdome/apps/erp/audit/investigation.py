"""Automated Transaction Investigation Engine.

Tools: audit_investigate_transaction
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

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def investigate_transaction(tool_input: Dict[str, Any]) -> str:
    """Deep-dive investigation of a transaction to check validity and fraud risk."""
    client = _get_client()
    doctype = tool_input["doctype"]
    name = tool_input["name"]
    objective = tool_input.get("objective", "General validity verification")

    try:
        # 1. Fetch document and history
        history_data = await client.get_doc_with_history(doctype, name)
        doc = history_data.get("document", {})
        versions = history_data.get("version_history", [])

        # 2. Get document timeline
        timeline = await client.get_doc_timeline(doctype, name)

        # 3. Find related documents
        # Check references in document structure
        related = []
        if doctype == "Payment Entry":
            # Search payment references
            refs = doc.get("references", [])
            for r in refs:
                if isinstance(r, dict) and r.get("reference_name"):
                    related.append({
                        "doctype": r.get("reference_doctype"),
                        "name": r.get("reference_name"),
                        "amount": r.get("allocated_amount"),
                    })
        elif doctype in ("Sales Invoice", "Purchase Invoice"):
            # Check items for references
            items = doc.get("items", [])
            for item in items:
                if isinstance(item, dict):
                    po = item.get("purchase_order") or item.get("sales_order")
                    receipt = item.get("purchase_receipt") or item.get("delivery_note")
                    if po:
                        related.append({"doctype": "Purchase Order" if "purchase" in doctype.lower() else "Sales Order", "name": po})
                    if receipt:
                        related.append({"doctype": "Purchase Receipt" if "purchase" in doctype.lower() else "Delivery Note", "name": receipt})

        # 4. Check approvals
        workflow_actions = await client.get_list(
            "Workflow Action",
            filters={"reference_doctype": doctype, "reference_name": name},
            fields=["workflow_state", "status", "user", "creation"],
        )

        # 5. Check anomalies
        warnings = []
        findings = []

        # Check post-submission modifications
        if doc.get("docstatus") == 1 and versions:
            warnings.append("Document was modified after final submission/approval.")

        # Check direct Admin postings
        creator = doc.get("owner", "")
        if creator in ("Administrator", "Administrator@example.com"):
            warnings.append("Document created by Administrator account (potential override).")

        # Compile final audit reasoning
        confidence = Confidence.HIGH
        audit_reasoning = f"Performed deep investigation for {doctype} {name} to verify {objective}."

        if warnings:
            findings.append(AuditFinding(
                title=f"Investigation Warning: {doctype} {name}",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.ACCURACY],
                observation=f"Anomalies detected during transaction deep-dive: {'; '.join(warnings)}",
                audit_reasoning=audit_reasoning,
                recommendation="Examine support files and authorization emails manually.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={
                "objective": objective,
                "document": doc,
                "version_count": len(versions),
                "timeline": timeline,
                "related_documents": related,
                "workflow_actions": workflow_actions,
            },
            evidence_source=f"{doctype}/{name}",
            confidence=confidence,
            warnings=warnings,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Transaction investigation failed: {e}"],
        ))
