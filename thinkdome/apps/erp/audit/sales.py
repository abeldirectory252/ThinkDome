"""Revenue / sales audit tools.

Tools: audit_get_sales_cycle, audit_find_invoice_without_delivery,
       audit_find_delivery_without_invoice, audit_find_revenue_cutoff_errors,
       audit_find_unusual_sales
"""

from __future__ import annotations

import json
import logging
import statistics
from typing import Any, Dict, List

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditAssertion,
    Confidence,
    RiskRating,
    audit_response,
)
from thinkdome.apps.erp.audit.config import get_materiality_threshold

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_sales_cycle(tool_input: Dict[str, Any]) -> str:
    """Trace the full sales cycle: SO → DN → SI → Payment for a given document."""
    client = _get_client()
    name = tool_input["name"]

    try:
        # Try to find the starting document in various doctypes
        cycle: Dict[str, Any] = {"sales_orders": [], "delivery_notes": [], "sales_invoices": [], "payments": []}

        # Sales Order
        try:
            so = await client.get_doc("Sales Order", name)
            cycle["sales_orders"].append(so)
        except Exception:
            pass

        # Search by reference chain — find linked delivery notes
        dn_items = await client.get_list(
            "Delivery Note Item",
            filters={"against_sales_order": name},
            fields=["parent", "parenttype"],
        )
        dn_names = list({d.get("parent") for d in dn_items if d.get("parent")})
        for dn_name in dn_names:
            try:
                dn = await client.get_doc("Delivery Note", dn_name)
                cycle["delivery_notes"].append(dn)
            except Exception:
                pass

        # Find linked sales invoices
        si_items = await client.get_list(
            "Sales Invoice Item",
            filters={"sales_order": name},
            fields=["parent", "parenttype"],
        )
        si_names = list({s.get("parent") for s in si_items if s.get("parent")})
        for si_name in si_names:
            try:
                si = await client.get_doc("Sales Invoice", si_name)
                cycle["sales_invoices"].append(si)
            except Exception:
                pass

        # Find payments
        for si_name in si_names:
            pe_refs = await client.get_list(
                "Payment Entry Reference",
                filters={"reference_doctype": "Sales Invoice", "reference_name": si_name},
                fields=["parent"],
            )
            for ref in pe_refs:
                try:
                    pe = await client.get_doc("Payment Entry", ref.get("parent"))
                    cycle["payments"].append(pe)
                except Exception:
                    pass

        warnings = []
        if not cycle["delivery_notes"]:
            warnings.append("No Delivery Notes found in sales cycle. Revenue may be recognized without delivery.")
        if not cycle["payments"]:
            warnings.append("No payments found. Outstanding receivable requires aging analysis.")

        return json.dumps(audit_response(
            data=cycle,
            evidence_source=f"Sales Order/{name} cycle",
            confidence=Confidence.HIGH if cycle["sales_orders"] else Confidence.MEDIUM,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Sales Cycle",
            confidence=Confidence.LOW, warnings=[f"Sales cycle trace failed: {e}"],
        ))


async def find_invoice_without_delivery(tool_input: Dict[str, Any]) -> str:
    """Find sales invoices with no linked delivery note (revenue without delivery)."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1, "is_return": 0}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Sales Invoice",
            filters=filters,
            fields=["name", "customer", "posting_date", "grand_total", "owner",
                    "update_stock", "creation"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        no_delivery = []
        for inv in invoices:
            # Check if update_stock is set (direct stock deduction, no DN needed)
            if inv.get("update_stock"):
                continue

            # Check for linked delivery notes via items
            items = await client.get_list(
                "Sales Invoice Item",
                filters={"parent": inv["name"]},
                fields=["delivery_note", "so_detail"],
            )
            has_dn = any(it.get("delivery_note") for it in items)
            if not has_dn:
                no_delivery.append(inv)

        findings = []
        if no_delivery:
            findings.append(AuditFinding(
                title="Sales Invoices Without Delivery Notes",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.EXISTENCE],
                observation=f"{len(no_delivery)} sales invoices have no linked delivery note.",
                audit_reasoning="Revenue recognized without evidence of goods delivery may indicate fictitious sales.",
                recommendation="Verify delivery for each invoice. Obtain alternative proof of delivery.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"invoices_without_delivery": no_delivery, "count": len(no_delivery)},
            evidence_source="Sales Invoice / Sales Invoice Item",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Sales Invoice",
            confidence=Confidence.LOW, warnings=[f"Search failed: {e}"],
        ))


async def find_delivery_without_invoice(tool_input: Dict[str, Any]) -> str:
    """Find delivery notes with no matching sales invoice."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        delivery_notes = await client.get_list(
            "Delivery Note",
            filters=filters,
            fields=["name", "customer", "posting_date", "grand_total", "per_billed",
                    "owner", "creation"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        # Filter those not fully billed
        unbilled = [dn for dn in delivery_notes if float(dn.get("per_billed", 0) or 0) < 100]

        findings = []
        if unbilled:
            findings.append(AuditFinding(
                title="Delivery Notes Not Fully Invoiced",
                risk_rating=RiskRating.MEDIUM,
                assertions=[AuditAssertion.COMPLETENESS, AuditAssertion.CUTOFF],
                observation=f"{len(unbilled)} delivery notes are not fully billed.",
                audit_reasoning="Goods delivered but not invoiced may indicate revenue understatement.",
                recommendation="Investigate unbilled deliveries. Determine if revenue should be recognized.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"unbilled_deliveries": unbilled, "count": len(unbilled)},
            evidence_source="Delivery Note",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Delivery Note",
            confidence=Confidence.LOW, warnings=[f"Search failed: {e}"],
        ))


async def find_revenue_cutoff_errors(tool_input: Dict[str, Any]) -> str:
    """Find invoices where posting date is inconsistent with delivery date."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Sales Invoice",
            filters=filters,
            fields=["name", "customer", "posting_date", "grand_total", "creation"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        cutoff_issues = []
        for inv in invoices:
            items = await client.get_list(
                "Sales Invoice Item",
                filters={"parent": inv["name"]},
                fields=["delivery_note", "dn_detail"],
            )
            for item in items:
                dn_name = item.get("delivery_note")
                if dn_name:
                    try:
                        dn = await client.get_doc("Delivery Note", dn_name)
                        dn_date = str(dn.get("posting_date", ""))[:10]
                        inv_date = str(inv.get("posting_date", ""))[:10]
                        if dn_date and inv_date and inv_date < dn_date:
                            cutoff_issues.append({
                                "invoice": inv["name"],
                                "invoice_date": inv_date,
                                "delivery_note": dn_name,
                                "delivery_date": dn_date,
                                "amount": inv.get("grand_total"),
                                "issue": "Invoice dated before delivery",
                            })
                    except Exception:
                        pass

        findings = []
        if cutoff_issues:
            findings.append(AuditFinding(
                title="Revenue Cutoff Errors Detected",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.CUTOFF, AuditAssertion.OCCURRENCE],
                observation=f"{len(cutoff_issues)} invoices are dated before their delivery notes.",
                audit_reasoning="Invoicing before delivery indicates premature revenue recognition.",
                recommendation="Adjust revenue to the correct period based on delivery dates.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"cutoff_issues": cutoff_issues, "count": len(cutoff_issues)},
            evidence_source="Sales Invoice / Delivery Note",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Sales Invoice",
            confidence=Confidence.LOW, warnings=[f"Cutoff analysis failed: {e}"],
        ))


async def find_unusual_sales(tool_input: Dict[str, Any]) -> str:
    """Find statistically unusual sales transactions (outliers)."""
    client = _get_client()
    threshold = tool_input.get("threshold") or get_materiality_threshold()

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Sales Invoice",
            filters=filters,
            fields=["name", "customer", "posting_date", "grand_total", "owner", "creation"],
            order_by="grand_total desc",
            limit_page_length=tool_input.get("limit", 500),
        )

        amounts = [float(i.get("grand_total", 0) or 0) for i in invoices if float(i.get("grand_total", 0) or 0) > 0]

        unusual = []
        if len(amounts) >= 3:
            mean = statistics.mean(amounts)
            stdev = statistics.stdev(amounts)
            upper_bound = mean + 3 * stdev if stdev > 0 else mean * 2

            for inv in invoices:
                amount = float(inv.get("grand_total", 0) or 0)
                if amount >= upper_bound or amount >= threshold * 10:
                    inv["_z_score"] = round((amount - mean) / stdev, 2) if stdev > 0 else 0
                    unusual.append(inv)

        return json.dumps(audit_response(
            data={
                "unusual_sales": unusual,
                "count": len(unusual),
                "statistics": {
                    "mean": round(statistics.mean(amounts), 2) if amounts else 0,
                    "stdev": round(statistics.stdev(amounts), 2) if len(amounts) >= 2 else 0,
                    "total_invoices": len(invoices),
                },
            },
            evidence_source="Sales Invoice",
            confidence=Confidence.MEDIUM,
            warnings=[f"Found {len(unusual)} statistically unusual sales transactions."] if unusual else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Sales Invoice",
            confidence=Confidence.LOW, warnings=[f"Unusual sales analysis failed: {e}"],
        ))
