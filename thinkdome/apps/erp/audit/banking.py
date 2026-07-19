"""Banking and cash transaction audit tools.

Tools: audit_get_bank_reconciliation, audit_find_unreconciled_transactions,
       audit_find_cash_transactions, audit_find_duplicate_payments
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
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


async def get_bank_reconciliation(tool_input: Dict[str, Any]) -> str:
    """Fetch details of bank reconciliation state and cleared vouchers."""
    client = _get_client()
    bank_account = tool_input.get("bank_account")

    try:
        filters: Dict[str, Any] = {}
        if bank_account:
            filters["bank_account"] = bank_account
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        # In ERPNext, Bank Reconciliation status is tracked on Bank Transaction level
        # and through Bank Clearance / Bank Guarantee documents.
        # We retrieve the bank transactions to see what is cleared vs uncleared.
        transactions = await client.get_list(
            "Bank Transaction",
            filters=filters,
            fields=["name", "bank_account", "date", "deposit", "withdrawal",
                    "status", "clearance_date", "company", "owner"],
            order_by="date desc",
            limit_page_length=500,
        )

        total_deposit = 0.0
        total_withdrawal = 0.0
        cleared_count = 0
        uncleared_count = 0

        for t in transactions:
            deposit = float(t.get("deposit", 0) or 0)
            withdrawal = float(t.get("withdrawal", 0) or 0)
            total_deposit += deposit
            total_withdrawal += withdrawal
            if t.get("status") == "Cleared":
                cleared_count += 1
            else:
                uncleared_count += 1

        summary = {
            "total_transactions_checked": len(transactions),
            "total_deposit_amount": total_deposit,
            "total_withdrawal_amount": total_withdrawal,
            "cleared_count": cleared_count,
            "uncleared_count": uncleared_count,
        }

        return json.dumps(audit_response(
            data={"summary": summary, "transactions": transactions},
            evidence_source="Bank Transaction",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Bank Transaction",
            confidence=Confidence.LOW, warnings=[f"Failed to check bank reconciliation: {e}"],
        ))


async def find_unreconciled_transactions(tool_input: Dict[str, Any]) -> str:
    """Find stale unreconciled bank transactions or ledger entries."""
    client = _get_client()
    stale_days = get_thresholds().get("stale_reconciliation_days", 90)

    try:
        filters: Dict[str, Any] = {"status": ["!=", "Cleared"]}
        if tool_input.get("bank_account"):
            filters["bank_account"] = tool_input["bank_account"]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        transactions = await client.get_list(
            "Bank Transaction",
            filters=filters,
            fields=["name", "bank_account", "date", "deposit", "withdrawal", "status", "company", "creation"],
            order_by="date asc",
            limit_page_length=200,
        )

        stale_transactions = []
        today = date.today()

        for t in transactions:
            t_date_str = str(t.get("date", ""))[:10]
            if t_date_str:
                try:
                    t_date = datetime.strptime(t_date_str, "%Y-%m-%d").date()
                    age = (today - t_date).days
                    if age >= stale_days:
                        t["_age_days"] = age
                        stale_transactions.append(t)
                except Exception:
                    pass

        findings = []
        if stale_transactions:
            findings.append(AuditFinding(
                title="Stale Unreconciled Bank Transactions",
                risk_rating=RiskRating.HIGH if len(stale_transactions) > 10 else RiskRating.MEDIUM,
                assertions=[AuditAssertion.EXISTENCE, AuditAssertion.COMPLETENESS],
                observation=f"{len(stale_transactions)} bank transactions have been unreconciled for >= {stale_days} days.",
                audit_reasoning="Stale unreconciled items are high risk; they may mask missing disbursements, errors, or unrecorded cash transactions.",
                recommendation="Investigate aging unreconciled transactions. Request matching bank statements and vouchers.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"stale_unreconciled_transactions": stale_transactions, "count": len(stale_transactions)},
            evidence_source="Bank Transaction",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Bank Transaction",
            confidence=Confidence.LOW, warnings=[f"Failed to find unreconciled transactions: {e}"],
        ))


async def find_cash_transactions(tool_input: Dict[str, Any]) -> str:
    """Identify entries posted directly against cash/petty cash accounts."""
    client = _get_client()

    try:
        # Find Cash accounts
        acc_filters: Dict[str, Any] = {"account_type": "Cash"}
        if tool_input.get("company"):
            acc_filters["company"] = tool_input["company"]

        cash_accounts = await client.get_list(
            "Account",
            filters=acc_filters,
            fields=["name", "company"],
        )

        cash_account_names = [a["name"] for a in cash_accounts]
        if not cash_account_names:
            return json.dumps(audit_response(
                data={"entries": [], "count": 0},
                evidence_source="GL Entry",
                confidence=Confidence.HIGH,
                warnings=["No Cash accounts defined in Chart of Accounts."],
            ))

        gl_filters: Dict[str, Any] = {
            "account": ["in", cash_account_names],
            "is_cancelled": 0,
        }
        if tool_input.get("from_date") and tool_input.get("to_date"):
            gl_filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            gl_filters["company"] = tool_input["company"]

        entries = await client.get_list(
            "GL Entry",
            filters=gl_filters,
            fields=["name", "posting_date", "account", "debit", "credit", "voucher_type", "voucher_no", "owner", "remarks"],
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        return json.dumps(audit_response(
            data={"entries": entries, "count": len(entries)},
            evidence_source="GL Entry / Account",
            confidence=Confidence.HIGH,
            warnings=[f"Identified {len(entries)} direct cash/petty cash ledger transactions. Cash requires tight custody verification."] if entries else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Failed to find cash transactions: {e}"],
        ))


async def find_duplicate_payments(tool_input: Dict[str, Any]) -> str:
    """Identify duplicate payment entries (same supplier/customer, amount, and date window)."""
    client = _get_client()
    window_days = get_thresholds().get("duplicate_date_window_days", 30)

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        payments = await client.get_list(
            "Payment Entry",
            filters=filters,
            fields=["name", "party_type", "party", "posting_date", "paid_amount", "reference_no", "owner", "creation"],
            order_by="party asc, posting_date asc",
            limit_page_length=500,
        )

        duplicates = []
        for i, pay_a in enumerate(payments):
            for pay_b in payments[i + 1:]:
                if pay_a.get("party") != pay_b.get("party"):
                    break  # Sorted by party, stop check

                amount_a = float(pay_a.get("paid_amount", 0) or 0)
                amount_b = float(pay_b.get("paid_amount", 0) or 0)
                if abs(amount_a - amount_b) > 0.01:
                    continue

                try:
                    date_a = datetime.strptime(str(pay_a.get("posting_date", ""))[:10], "%Y-%m-%d").date()
                    date_b = datetime.strptime(str(pay_b.get("posting_date", ""))[:10], "%Y-%m-%d").date()
                    if abs((date_b - date_a).days) <= window_days:
                        duplicates.append({
                            "payment_a": pay_a["name"],
                            "payment_b": pay_b["name"],
                            "party_type": pay_a.get("party_type"),
                            "party": pay_a.get("party"),
                            "amount": amount_a,
                            "date_a": str(pay_a.get("posting_date", ""))[:10],
                            "date_b": str(pay_b.get("posting_date", ""))[:10],
                            "ref_no_a": pay_a.get("reference_no"),
                            "ref_no_b": pay_b.get("reference_no"),
                        })
                except Exception:
                    pass

        findings = []
        if duplicates:
            findings.append(AuditFinding(
                title="Duplicate Payments Detected",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.ACCURACY],
                observation=f"{len(duplicates)} pairs of potential duplicate payments to customers/suppliers detected.",
                audit_reasoning="Duplicate payments represent internal control breakdowns and direct cash flow leakage.",
                recommendation="Investigate matching payment transactions and cross-reference with bank reconciliation clearances.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"duplicates": duplicates, "count": len(duplicates)},
            evidence_source="Payment Entry",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Payment Entry",
            confidence=Confidence.LOW, warnings=[f"Duplicate payment check failed: {e}"],
        ))
