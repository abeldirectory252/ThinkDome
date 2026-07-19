"""Purchase / procurement audit tools.

Tools: audit_get_purchase_cycle, audit_test_three_way_matching,
       audit_find_duplicate_supplier_invoice, audit_find_payment_without_invoice,
       audit_find_invoice_without_po
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


async def get_purchase_cycle(tool_input: Dict[str, Any]) -> str:
    """Trace the full purchase cycle: PO → PR → PI → Payment."""
    client = _get_client()
    name = tool_input["name"]

    try:
        cycle: Dict[str, Any] = {
            "purchase_orders": [], "purchase_receipts": [],
            "purchase_invoices": [], "payments": [],
        }

        try:
            po = await client.get_doc("Purchase Order", name)
            cycle["purchase_orders"].append(po)
        except Exception:
            pass

        # Purchase Receipts linked to PO
        pr_items = await client.get_list(
            "Purchase Receipt Item",
            filters={"purchase_order": name},
            fields=["parent"],
        )
        pr_names = list({p.get("parent") for p in pr_items if p.get("parent")})
        for pr_name in pr_names:
            try:
                cycle["purchase_receipts"].append(await client.get_doc("Purchase Receipt", pr_name))
            except Exception:
                pass

        # Purchase Invoices linked to PO
        pi_items = await client.get_list(
            "Purchase Invoice Item",
            filters={"purchase_order": name},
            fields=["parent"],
        )
        pi_names = list({p.get("parent") for p in pi_items if p.get("parent")})
        for pi_name in pi_names:
            try:
                cycle["purchase_invoices"].append(await client.get_doc("Purchase Invoice", pi_name))
            except Exception:
                pass

        # Payments for invoices
        for pi_name in pi_names:
            pe_refs = await client.get_list(
                "Payment Entry Reference",
                filters={"reference_doctype": "Purchase Invoice", "reference_name": pi_name},
                fields=["parent"],
            )
            for ref in pe_refs:
                try:
                    cycle["payments"].append(await client.get_doc("Payment Entry", ref.get("parent")))
                except Exception:
                    pass

        warnings = []
        if not cycle["purchase_receipts"]:
            warnings.append("No Purchase Receipts found. Goods receipt may not have been verified.")
        if cycle["purchase_invoices"] and not cycle["purchase_orders"]:
            warnings.append("Invoice exists without Purchase Order. Procurement may have bypassed approval.")

        return json.dumps(audit_response(
            data=cycle,
            evidence_source=f"Purchase Order/{name} cycle",
            confidence=Confidence.HIGH if cycle["purchase_orders"] else Confidence.MEDIUM,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Purchase Cycle",
            confidence=Confidence.LOW, warnings=[f"Purchase cycle trace failed: {e}"],
        ))


async def test_three_way_matching(tool_input: Dict[str, Any]) -> str:
    """Test three-way matching: PO quantity/price vs PR quantity vs PI quantity/price."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("supplier"):
            filters["supplier"] = tool_input["supplier"]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Purchase Invoice",
            filters=filters,
            fields=["name", "supplier", "posting_date", "grand_total"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 100),
        )

        match_results = []
        for inv in invoices:
            items = await client.get_list(
                "Purchase Invoice Item",
                filters={"parent": inv["name"]},
                fields=["item_code", "qty", "rate", "amount",
                        "purchase_order", "po_detail",
                        "purchase_receipt", "pr_detail"],
            )

            for item in items:
                result = {
                    "invoice": inv["name"],
                    "item_code": item.get("item_code"),
                    "pi_qty": float(item.get("qty", 0) or 0),
                    "pi_rate": float(item.get("rate", 0) or 0),
                    "pi_amount": float(item.get("amount", 0) or 0),
                    "has_po": bool(item.get("purchase_order")),
                    "has_pr": bool(item.get("purchase_receipt")),
                    "po_match": None,
                    "pr_match": None,
                    "discrepancies": [],
                }

                # Check PO match
                if item.get("purchase_order") and item.get("po_detail"):
                    try:
                        po_item = await client.get_doc("Purchase Order Item", item["po_detail"])
                        po_qty = float(po_item.get("qty", 0) or 0)
                        po_rate = float(po_item.get("rate", 0) or 0)
                        result["po_qty"] = po_qty
                        result["po_rate"] = po_rate
                        if abs(result["pi_qty"] - po_qty) > 0.01:
                            result["discrepancies"].append(f"Qty mismatch: PO={po_qty}, PI={result['pi_qty']}")
                        if abs(result["pi_rate"] - po_rate) > 0.01:
                            result["discrepancies"].append(f"Rate mismatch: PO={po_rate}, PI={result['pi_rate']}")
                        result["po_match"] = len(result["discrepancies"]) == 0
                    except Exception:
                        result["discrepancies"].append("Unable to verify PO item")

                # Check PR match
                if item.get("purchase_receipt") and item.get("pr_detail"):
                    try:
                        pr_item = await client.get_doc("Purchase Receipt Item", item["pr_detail"])
                        pr_qty = float(pr_item.get("qty", 0) or 0)
                        result["pr_qty"] = pr_qty
                        if abs(result["pi_qty"] - pr_qty) > 0.01:
                            result["discrepancies"].append(f"Receipt qty mismatch: PR={pr_qty}, PI={result['pi_qty']}")
                        result["pr_match"] = abs(result["pi_qty"] - pr_qty) <= 0.01
                    except Exception:
                        result["discrepancies"].append("Unable to verify PR item")

                if not result["has_po"]:
                    result["discrepancies"].append("No Purchase Order linked")
                if not result["has_pr"]:
                    result["discrepancies"].append("No Purchase Receipt linked")

                match_results.append(result)

        failed = [r for r in match_results if r.get("discrepancies")]

        findings = []
        if failed:
            findings.append(AuditFinding(
                title="Three-Way Matching Failures",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.ACCURACY, AuditAssertion.EXISTENCE],
                observation=f"{len(failed)} of {len(match_results)} line items failed three-way matching.",
                audit_reasoning="Matching failures indicate potential unauthorized purchases, price overrides, or quantity discrepancies.",
                recommendation="Investigate each discrepancy. Verify supporting documentation.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={
                "match_results": match_results,
                "total_items": len(match_results),
                "failed_items": len(failed),
                "pass_rate": round((len(match_results) - len(failed)) / max(len(match_results), 1) * 100, 1),
            },
            evidence_source="Purchase Invoice Item / Purchase Order Item / Purchase Receipt Item",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Three-Way Matching",
            confidence=Confidence.LOW, warnings=[f"Three-way matching test failed: {e}"],
        ))


async def find_duplicate_supplier_invoice(tool_input: Dict[str, Any]) -> str:
    """Detect potential duplicate supplier invoices (same supplier + similar amount + date window)."""
    client = _get_client()
    from thinkdome.apps.erp.audit.config import get_thresholds
    window_days = get_thresholds().get("duplicate_date_window_days", 30)

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Purchase Invoice",
            filters=filters,
            fields=["name", "supplier", "supplier_name", "posting_date",
                    "grand_total", "bill_no", "bill_date", "owner", "creation"],
            order_by="supplier asc, posting_date asc",
            limit_page_length=tool_input.get("limit", 500),
        )

        # Group by supplier and check for duplicates
        from datetime import datetime as dt, timedelta
        duplicates = []
        for i, inv_a in enumerate(invoices):
            for inv_b in invoices[i + 1:]:
                if inv_a.get("supplier") != inv_b.get("supplier"):
                    break  # Sorted by supplier, no more matches
                # Same supplier — check amount and date proximity
                amount_a = float(inv_a.get("grand_total", 0) or 0)
                amount_b = float(inv_b.get("grand_total", 0) or 0)
                if abs(amount_a - amount_b) > 0.01:
                    continue
                try:
                    date_a = dt.strptime(str(inv_a.get("posting_date", ""))[:10], "%Y-%m-%d")
                    date_b = dt.strptime(str(inv_b.get("posting_date", ""))[:10], "%Y-%m-%d")
                    if abs((date_b - date_a).days) <= window_days:
                        duplicates.append({
                            "invoice_a": inv_a["name"],
                            "invoice_b": inv_b["name"],
                            "supplier": inv_a.get("supplier"),
                            "amount": amount_a,
                            "date_a": str(inv_a.get("posting_date", ""))[:10],
                            "date_b": str(inv_b.get("posting_date", ""))[:10],
                            "bill_no_a": inv_a.get("bill_no"),
                            "bill_no_b": inv_b.get("bill_no"),
                            "same_bill_no": inv_a.get("bill_no") == inv_b.get("bill_no") and bool(inv_a.get("bill_no")),
                        })
                except (ValueError, TypeError):
                    continue

        findings = []
        if duplicates:
            high_risk = [d for d in duplicates if d.get("same_bill_no")]
            findings.append(AuditFinding(
                title="Potential Duplicate Supplier Invoices",
                risk_rating=RiskRating.CRITICAL if high_risk else RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.ACCURACY],
                observation=f"{len(duplicates)} potential duplicate invoice pairs detected ({len(high_risk)} with same bill number).",
                audit_reasoning="Duplicate invoices may result in duplicate payments to suppliers — a significant fraud risk.",
                recommendation="Verify each pair. Confirm whether duplicate payment was made. Recover overpayments.",
                confidence=Confidence.HIGH if high_risk else Confidence.MEDIUM,
            ))

        return json.dumps(audit_response(
            data={"duplicates": duplicates, "count": len(duplicates)},
            evidence_source="Purchase Invoice",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Purchase Invoice",
            confidence=Confidence.LOW, warnings=[f"Duplicate invoice detection failed: {e}"],
        ))


async def find_payment_without_invoice(tool_input: Dict[str, Any]) -> str:
    """Find payments to suppliers with no linked purchase invoice."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1, "payment_type": "Pay"}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        payments = await client.get_list(
            "Payment Entry",
            filters=filters,
            fields=["name", "party_type", "party", "paid_amount", "posting_date",
                    "owner", "creation", "mode_of_payment"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        no_invoice = []
        for pe in payments:
            refs = await client.get_list(
                "Payment Entry Reference",
                filters={"parent": pe["name"]},
                fields=["reference_doctype", "reference_name"],
            )
            has_invoice = any(
                r.get("reference_doctype") in ("Purchase Invoice", "Sales Invoice")
                for r in refs
            )
            if not has_invoice:
                pe["_references"] = refs
                no_invoice.append(pe)

        findings = []
        if no_invoice:
            findings.append(AuditFinding(
                title="Payments Without Invoice Reference",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.EXISTENCE],
                observation=f"{len(no_invoice)} payments have no linked invoice.",
                audit_reasoning="Payments without invoices bypass normal procurement controls and may indicate unauthorized disbursements.",
                recommendation="Verify the business purpose. Obtain supporting documentation.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"payments_without_invoice": no_invoice, "count": len(no_invoice)},
            evidence_source="Payment Entry / Payment Entry Reference",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Payment Entry",
            confidence=Confidence.LOW, warnings=[f"Payment analysis failed: {e}"],
        ))


async def find_invoice_without_po(tool_input: Dict[str, Any]) -> str:
    """Find purchase invoices that bypass the PO process."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        invoices = await client.get_list(
            "Purchase Invoice",
            filters=filters,
            fields=["name", "supplier", "posting_date", "grand_total", "owner", "creation"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        no_po = []
        for inv in invoices:
            items = await client.get_list(
                "Purchase Invoice Item",
                filters={"parent": inv["name"]},
                fields=["purchase_order"],
            )
            has_po = any(it.get("purchase_order") for it in items)
            if not has_po:
                no_po.append(inv)

        findings = []
        if no_po:
            findings.append(AuditFinding(
                title="Purchase Invoices Without Purchase Orders",
                risk_rating=RiskRating.MEDIUM,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.COMPLETENESS],
                observation=f"{len(no_po)} purchase invoices have no linked Purchase Order.",
                audit_reasoning="Invoices without POs indicate procurement outside normal approval channels.",
                recommendation="Verify authorization for each invoice. Assess if PO requirement was properly waived.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"invoices_without_po": no_po, "count": len(no_po)},
            evidence_source="Purchase Invoice / Purchase Invoice Item",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Purchase Invoice",
            confidence=Confidence.LOW, warnings=[f"PO linkage analysis failed: {e}"],
        ))
