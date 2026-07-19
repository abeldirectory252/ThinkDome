"""Journal entry audit tools.

Tools: audit_get_journal_entry, audit_get_journal_history,
       audit_get_journal_creator, audit_get_journal_approvals,
       audit_get_related_documents
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import Confidence, audit_response

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_journal_entry(tool_input: Dict[str, Any]) -> str:
    """Fetch full journal entry with lines, attachments, and linked documents."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Journal Entry")
    name = tool_input["name"]

    try:
        doc = await client.get_doc(doctype, name)

        # Fetch attachments
        attachments = await client.get_list(
            "File",
            filters={"attached_to_doctype": doctype, "attached_to_name": name},
            fields=["name", "file_name", "file_url", "file_size", "creation", "owner"],
        )

        return json.dumps(audit_response(
            data={
                "journal_entry": doc,
                "attachments": attachments,
                "attachment_count": len(attachments),
            },
            evidence_source=f"{doctype}/{name}",
            confidence=Confidence.HIGH,
            warnings=["No attachments found — supporting documentation may be missing."] if not attachments else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch journal entry: {e}"],
        ))


async def get_journal_history(tool_input: Dict[str, Any]) -> str:
    """Fetch version history and all modifications for a journal entry."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Journal Entry")
    name = tool_input["name"]

    try:
        versions = await client.get_version_log(doctype, name)

        warnings = []
        if versions:
            warnings.append(
                f"Document has {len(versions)} version(s). "
                "Post-creation modifications to journal entries require scrutiny."
            )

        return json.dumps(audit_response(
            data={"version_history": versions, "modification_count": len(versions)},
            evidence_source=f"Version/{doctype}/{name}",
            confidence=Confidence.HIGH,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"Version/{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch journal history: {e}"],
        ))


async def get_journal_creator(tool_input: Dict[str, Any]) -> str:
    """Identify who created a journal entry, when, and with what role."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Journal Entry")
    name = tool_input["name"]

    try:
        doc = await client.get_doc(doctype, name)

        creator = doc.get("owner", "Unknown")
        creation = doc.get("creation", "Unknown")
        modified_by = doc.get("modified_by", "Unknown")
        modified = doc.get("modified", "Unknown")

        # Check if creator has elevated roles
        warnings = []
        try:
            user_doc = await client.get_doc("User", creator)
            user_roles = [r.get("role") for r in user_doc.get("roles", []) if isinstance(r, dict)]
            if "Administrator" in user_roles or "System Manager" in user_roles:
                warnings.append(
                    f"Journal entry created by privileged user '{creator}' "
                    f"with roles: {', '.join(user_roles)}. "
                    "Entries by privileged users require enhanced scrutiny."
                )
        except Exception:
            warnings.append(f"Unable to verify roles for user '{creator}'.")

        return json.dumps(audit_response(
            data={
                "creator": creator,
                "creation_date": creation,
                "last_modified_by": modified_by,
                "last_modified_date": modified,
                "docstatus": doc.get("docstatus"),
            },
            evidence_source=f"{doctype}/{name}",
            confidence=Confidence.HIGH,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch creator info: {e}"],
        ))


async def get_journal_approvals(tool_input: Dict[str, Any]) -> str:
    """Fetch the approval workflow trail for a journal entry."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Journal Entry")
    name = tool_input["name"]

    try:
        doc = await client.get_doc(doctype, name)

        # Workflow actions
        workflow_actions = await client.get_list(
            "Workflow Action",
            filters={"reference_doctype": doctype, "reference_name": name},
            fields=["name", "workflow_state", "status", "user", "creation", "completed_by"],
            order_by="creation asc",
        )

        # Comments (submission/approval comments)
        comments = await client.get_list(
            "Comment",
            filters={
                "reference_doctype": doctype,
                "reference_name": name,
                "comment_type": ["in", ["Workflow", "Submission", "Like", "Comment"]],
            },
            fields=["name", "owner", "creation", "content", "comment_type"],
            order_by="creation asc",
        )

        warnings = []
        if doc.get("docstatus") == 1 and not workflow_actions:
            warnings.append(
                "Document is submitted but no workflow actions found. "
                "This may indicate direct submission without approval workflow."
            )

        return json.dumps(audit_response(
            data={
                "docstatus": doc.get("docstatus"),
                "workflow_state": doc.get("workflow_state"),
                "workflow_actions": workflow_actions,
                "comments": comments,
            },
            evidence_source=f"Workflow Action / Comment / {doctype}/{name}",
            confidence=Confidence.HIGH if workflow_actions else Confidence.MEDIUM,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch approvals: {e}"],
        ))


async def get_related_documents(tool_input: Dict[str, Any]) -> str:
    """Find all documents linked to a journal entry (POs, invoices, payments)."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Journal Entry")
    name = tool_input["name"]

    try:
        doc = await client.get_doc(doctype, name)

        related = []

        # Check JE accounts table for references
        accounts = doc.get("accounts", [])
        if isinstance(accounts, list):
            for acc in accounts:
                if isinstance(acc, dict):
                    ref_type = acc.get("reference_type")
                    ref_name = acc.get("reference_name")
                    if ref_type and ref_name:
                        related.append({
                            "doctype": ref_type,
                            "name": ref_name,
                            "relationship": "reference",
                            "account": acc.get("account"),
                        })

        # GL entries with same voucher
        gl_entries = await client.get_list(
            "GL Entry",
            filters={"voucher_type": doctype, "voucher_no": name, "is_cancelled": 0},
            fields=["name", "account", "debit", "credit", "party_type", "party", "against"],
            order_by="creation asc",
        )

        # Payment references
        payment_refs = await client.get_list(
            "Payment Entry Reference",
            filters={"reference_doctype": doctype, "reference_name": name},
            fields=["parent", "parenttype", "allocated_amount", "creation"],
        )
        for pr in payment_refs:
            related.append({
                "doctype": pr.get("parenttype", "Payment Entry"),
                "name": pr.get("parent"),
                "relationship": "payment_reference",
                "amount": pr.get("allocated_amount"),
            })

        return json.dumps(audit_response(
            data={
                "related_documents": related,
                "gl_entries": gl_entries,
                "gl_entry_count": len(gl_entries),
            },
            evidence_source=f"{doctype}/{name} / GL Entry / Payment Entry Reference",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=f"{doctype}/{name}",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch related documents: {e}"],
        ))
