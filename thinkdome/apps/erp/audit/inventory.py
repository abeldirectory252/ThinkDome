"""Inventory / stock audit tools.

Tools: audit_get_stock_ledger, audit_find_negative_inventory,
       audit_find_large_stock_adjustments, audit_inventory_valuation,
       audit_find_inventory_anomalies
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
from thinkdome.apps.erp.audit.config import get_thresholds

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_stock_ledger(tool_input: Dict[str, Any]) -> str:
    """Fetch stock ledger entries with filters."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"is_cancelled": 0}
        if tool_input.get("item_code"):
            filters["item_code"] = tool_input["item_code"]
        if tool_input.get("warehouse"):
            filters["warehouse"] = tool_input["warehouse"]
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        elif tool_input.get("from_date"):
            filters["posting_date"] = [">=", tool_input["from_date"]]
        elif tool_input.get("to_date"):
            filters["posting_date"] = ["<=", tool_input["to_date"]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        entries = await client.get_list(
            "Stock Ledger Entry",
            filters=filters,
            fields=[
                "name", "item_code", "warehouse", "posting_date", "posting_time",
                "actual_qty", "qty_after_transaction", "valuation_rate", "stock_value",
                "voucher_type", "voucher_no", "company", "creation", "owner"
            ],
            order_by="posting_date desc, posting_time desc, creation desc",
            limit_page_length=tool_input.get("limit", 500),
        )

        return json.dumps(audit_response(
            data={"entries": entries, "count": len(entries)},
            evidence_source="Stock Ledger Entry",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Stock Ledger Entry",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch stock ledger: {e}"],
        ))


async def find_negative_inventory(tool_input: Dict[str, Any]) -> str:
    """Find items/warehouses with negative stock balances."""
    client = _get_client()
    tolerance = get_thresholds().get("negative_stock_tolerance", 0.001)

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        # Fetch active stock levels via Bin (ERPNext stores warehouse-item balances here)
        bins = await client.get_list(
            "Bin",
            filters=filters,
            fields=["name", "item_code", "warehouse", "actual_qty", "valuation_rate", "stock_value"],
            limit_page_length=500,
        )

        negative = []
        for b in bins:
            qty = float(b.get("actual_qty", 0) or 0)
            if qty < -tolerance:
                negative.append(b)

        findings = []
        if negative:
            findings.append(AuditFinding(
                title="Negative Inventory Balances Detected",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.EXISTENCE, AuditAssertion.VALUATION],
                observation=f"{len(negative)} items/warehouses have negative stock quantities.",
                audit_reasoning="Negative stock points to timing issues, recording errors, or failure to post receipts before deliveries.",
                recommendation="Investigate stock records for negative balances, adjust transactions, and verify physical existence.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"negative_inventory": negative, "count": len(negative)},
            evidence_source="Bin",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Bin",
            confidence=Confidence.LOW, warnings=[f"Failed to analyze negative inventory: {e}"],
        ))


async def find_large_stock_adjustments(tool_input: Dict[str, Any]) -> str:
    """Find stock reconciliation entries or stock entries exceeding value thresholds."""
    client = _get_client()
    # Use materiality threshold or custom threshold if specified
    threshold = tool_input.get("threshold") or 5000.0

    try:
        # Check Stock Reconciliations
        recon_filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            recon_filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            recon_filters["company"] = tool_input["company"]

        reconciliations = await client.get_list(
            "Stock Reconciliation",
            filters=recon_filters,
            fields=["name", "posting_date", "posting_time", "difference_amount", "company", "owner", "creation"],
            limit_page_length=100,
        )

        large_recons = []
        for r in reconciliations:
            diff = abs(float(r.get("difference_amount", 0) or 0))
            if diff >= threshold:
                r["_abs_difference"] = diff
                large_recons.append(r)

        # Check Stock Entries of type 'Repack', 'Material Issue', 'Material Receipt' with large values
        se_filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            se_filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            se_filters["company"] = tool_input["company"]

        stock_entries = await client.get_list(
            "Stock Entry",
            filters=se_filters,
            fields=["name", "posting_date", "posting_time", "purpose", "total_outgoing_value", "total_incoming_value", "company", "owner"],
            limit_page_length=200,
        )

        large_entries = []
        for se in stock_entries:
            out_val = float(se.get("total_outgoing_value", 0) or 0)
            in_val = float(se.get("total_incoming_value", 0) or 0)
            max_val = max(out_val, in_val)
            if max_val >= threshold and se.get("purpose") in ("Material Issue", "Material Receipt", "Repack"):
                se["_value"] = max_val
                large_entries.append(se)

        findings = []
        total_large = len(large_recons) + len(large_entries)
        if total_large > 0:
            findings.append(AuditFinding(
                title="Large Inventory Adjustments",
                risk_rating=RiskRating.HIGH if any(x.get("_abs_difference", 0) > threshold * 5 for x in large_recons) else RiskRating.MEDIUM,
                assertions=[AuditAssertion.VALUATION, AuditAssertion.EXISTENCE],
                observation=f"Detected {len(large_recons)} large stock reconciliations and {len(large_entries)} stock entries exceeding {threshold:,.2f}.",
                audit_reasoning="Large stock adjustments may indicate physical stock shrinkage, misvaluation, or theft mask attempts.",
                recommendation="Perform physical verification checks on high-risk items, review approvals for reconciliations.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={
                "large_reconciliations": large_recons,
                "large_stock_entries": large_entries,
                "count": total_large,
                "threshold": threshold,
            },
            evidence_source="Stock Reconciliation / Stock Entry",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Stock Reconciliation",
            confidence=Confidence.LOW, warnings=[f"Failed to check stock adjustments: {e}"],
        ))


async def inventory_valuation(tool_input: Dict[str, Any]) -> str:
    """Compare inventory valuation settings against General Ledger values."""
    client = _get_client()

    try:
        # 1. Fetch total balance from Stock Ledger (sum of stock value for active warehouses/items)
        filters: Dict[str, Any] = {}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        bins = await client.get_list(
            "Bin",
            filters=filters,
            fields=["item_code", "warehouse", "actual_qty", "valuation_rate", "stock_value"],
            limit_page_length=500,
        )

        total_bin_value = sum(float(b.get("stock_value", 0) or 0) for b in bins)

        # 2. Fetch balance of Stock Account from Trial Balance / GL
        gl_filters: Dict[str, Any] = {"is_cancelled": 0}
        if tool_input.get("company"):
            gl_filters["company"] = tool_input["company"]
        # Find stock accounts
        stock_accounts = await client.get_list(
            "Account",
            filters={"account_type": "Stock", **({"company": tool_input["company"]} if tool_input.get("company") else {})},
            fields=["name", "company"],
        )

        gl_stock_value = 0.0
        details = []
        for acc in stock_accounts:
            # Get balance
            bal_resp = await client.call_method(
                "erpnext.accounts.utils.get_balance_on",
                {"account": acc["name"], "date": datetime.today().strftime("%Y-%m-%d")},
            )
            bal = float(bal_resp or 0)
            gl_stock_value += bal
            details.append({"account": acc["name"], "balance": bal})

        variance = abs(total_bin_value - gl_stock_value)
        warnings = []
        findings = []

        if variance > 10.0: # Variance threshold
            warnings.append(f"Discrepancy between Stock Ledger ({total_bin_value:,.2f}) and General Ledger ({gl_stock_value:,.2f}). Variance: {variance:,.2f}")
            findings.append(AuditFinding(
                title="Stock Ledger and General Ledger Variance",
                risk_rating=RiskRating.HIGH if variance > 5000 else RiskRating.MEDIUM,
                assertions=[AuditAssertion.VALUATION, AuditAssertion.COMPLETENESS],
                observation=f"Stock ledger total stock value is {total_bin_value:,.2f} while GL stock accounts total {gl_stock_value:,.2f}. Variance: {variance:,.2f}",
                audit_reasoning="Variance between sub-ledger and general ledger indicates potential posting errors, system sync issues, or manual journal bypass.",
                recommendation="Investigate the transaction mismatch between stock ledger entries and GL postings.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={
                "total_stock_ledger_value": total_bin_value,
                "total_gl_stock_value": gl_stock_value,
                "variance": variance,
                "stock_accounts": details,
            },
            evidence_source="Bin / Account / GL",
            confidence=Confidence.HIGH,
            warnings=warnings,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Bin / Account",
            confidence=Confidence.LOW, warnings=[f"Valuation check failed: {e}"],
        ))


async def find_inventory_anomalies(tool_input: Dict[str, Any]) -> str:
    """Detect anomalies like backdated stock movements, high-turnover/zero-value entries."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"is_cancelled": 0}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        entries = await client.get_list(
            "Stock Ledger Entry",
            filters=filters,
            fields=["name", "item_code", "warehouse", "posting_date", "actual_qty", "valuation_rate",
                    "voucher_type", "voucher_no", "creation", "owner"],
            order_by="creation desc",
            limit_page_length=500,
        )

        anomalies = []
        for e in entries:
            posting = e.get("posting_date")
            creation = e.get("creation")
            qty = float(e.get("actual_qty", 0) or 0)
            rate = float(e.get("valuation_rate", 0) or 0)

            # 1. Backdated Stock Movement
            if posting and creation:
                try:
                    post_dt = datetime.strptime(str(posting)[:10], "%Y-%m-%d").date()
                    create_dt = datetime.strptime(str(creation)[:10], "%Y-%m-%d").date()
                    gap = (create_dt - post_dt).days
                    if gap >= 7:
                        anomalies.append({
                            "entry": e["name"],
                            "item_code": e["item_code"],
                            "voucher": f"{e['voucher_type']}/{e['voucher_no']}",
                            "type": "Backdated stock movement",
                            "details": f"Posted on {posting} but created on {creation[:10]} ({gap} days gap)",
                        })
                except Exception:
                    pass

            # 2. Zero valuation rate on receipt
            if qty > 0 and rate == 0 and e.get("voucher_type") in ("Purchase Receipt", "Stock Entry"):
                anomalies.append({
                    "entry": e["name"],
                    "item_code": e["item_code"],
                    "voucher": f"{e['voucher_type']}/{e['voucher_no']}",
                    "type": "Zero value receipt",
                    "details": f"Received {qty} units with valuation rate of 0",
                })

        return json.dumps(audit_response(
            data={"anomalies": anomalies, "count": len(anomalies)},
            evidence_source="Stock Ledger Entry",
            confidence=Confidence.HIGH,
            warnings=[f"Found {len(anomalies)} stock entry anomalies."] if anomalies else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Stock Ledger Entry",
            confidence=Confidence.LOW, warnings=[f"Anomalies check failed: {e}"],
        ))
