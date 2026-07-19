"""Evidence collection and workpaper management tools.

Tools: audit_collect_evidence, audit_create_workpaper
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditEvidence,
    AuditWorkpaper,
    Confidence,
    audit_response,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def collect_evidence(tool_input: Dict[str, Any]) -> str:
    """Gather complete evidence package for a specific transaction."""
    client = _get_client()
    doctype = tool_input["doctype"]
    name = tool_input["name"]

    try:
        doc = await client.get_doc(doctype, name)

        # Retrieve attachments
        files = await client.get_list(
            "File",
            filters={"attached_to_doctype": doctype, "attached_to_name": name},
            fields=["file_name", "file_url", "file_size", "creation", "owner"],
        )

        evidence_items = []
        # Main document
        evidence_items.append(AuditEvidence(
            source=doctype,
            document_name=name,
            description=f"Transaction document metadata for {doctype}/{name}",
            data=doc,
        ))

        # Files / Attachments
        for f in files:
            evidence_items.append(AuditEvidence(
                source="File",
                document_name=f.get("file_name"),
                description=f"Attachment file: {f.get('file_url')}",
                data=f,
            ))

        return json.dumps(audit_response(
            data={"evidence_package": [e.model_dump() for e in evidence_items], "count": len(evidence_items)},
            evidence_source=f"{doctype}/{name}",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Evidence collection failed: {e}"],
        ))


async def create_workpaper(tool_input: Dict[str, Any]) -> str:
    """Create a structured audit workpaper summarizing testing procedures and results."""
    client = _get_client()

    try:
        # Build workpaper from input details
        wp = AuditWorkpaper(
            title=tool_input["title"],
            objective=tool_input.get("objective", ""),
            scope=tool_input.get("scope", ""),
            procedure=tool_input.get("procedure", ""),
            conclusion=tool_input.get("conclusion", ""),
        )

        # Collect evidence reference details if provided
        evidence_list = []
        for ref in tool_input.get("evidence_refs", []):
            if ":" in ref:
                dtype, dname = ref.split(":", 1)
                try:
                    doc = await client.get_doc(dtype, dname)
                    evidence_list.append(AuditEvidence(
                        source=dtype,
                        document_name=dname,
                        description=f"Verified reference: {dtype}/{dname}",
                        data=doc,
                    ))
                except Exception:
                    pass

        wp.evidence = evidence_list

        return json.dumps(audit_response(
            data=wp.model_dump(),
            evidence_source="Audit Workpaper Engine",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Audit Workpaper Engine",
            confidence=Confidence.LOW, warnings=[f"Workpaper creation failed: {e}"],
        ))
