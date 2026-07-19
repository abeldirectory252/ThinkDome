"""Financial statement audit tools.

Tools: audit_get_trial_balance, audit_get_balance_sheet, audit_get_profit_loss,
       audit_get_cash_flow, audit_compare_financial_periods
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditFinding,
    AuditEvidence,
    AuditAssertion,
    Confidence,
    RiskRating,
    DateRangeInput,
    PeriodCompareInput,
    CompanyInput,
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


async def get_trial_balance(tool_input: Dict[str, Any]) -> str:
    """Fetch trial balance for the specified period."""
    client = _get_client()

    try:
        filters = {
            "from_date": tool_input["from_date"],
            "to_date": tool_input["to_date"],
        }
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        result = await client.run_report("Trial Balance", filters)

        # Check for imbalances
        warnings = []
        report_data = result.get("message", result) if isinstance(result, dict) else result
        rows = []
        if isinstance(report_data, dict):
            rows = report_data.get("result", [])

        total_debit = 0.0
        total_credit = 0.0
        for row in rows:
            if isinstance(row, dict):
                total_debit += float(row.get("debit", 0) or 0)
                total_credit += float(row.get("credit", 0) or 0)

        imbalance = abs(total_debit - total_credit)
        if imbalance > 0.01:
            warnings.append(
                f"MATERIAL CONCERN: Trial balance does not balance. "
                f"Debit={total_debit:.2f}, Credit={total_credit:.2f}, "
                f"Difference={imbalance:.2f}"
            )

        return json.dumps(audit_response(
            data={
                "report": report_data,
                "totals": {"total_debit": total_debit, "total_credit": total_credit, "imbalance": imbalance},
            },
            evidence_source="Trial Balance Report",
            confidence=Confidence.HIGH if imbalance <= 0.01 else Confidence.MEDIUM,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Trial Balance Report",
            confidence=Confidence.LOW,
            warnings=[f"Failed to generate trial balance: {e}"],
        ))


async def get_balance_sheet(tool_input: Dict[str, Any]) -> str:
    """Fetch balance sheet as of a specific date."""
    client = _get_client()

    try:
        filters = {
            "from_date": tool_input["from_date"],
            "to_date": tool_input["to_date"],
        }
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]
        filters["report_type"] = "Balance Sheet"

        result = await client.run_report("Balance Sheet", filters)

        return json.dumps(audit_response(
            data=result.get("message", result),
            evidence_source="Balance Sheet Report",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Balance Sheet Report",
            confidence=Confidence.LOW,
            warnings=[f"Failed to generate balance sheet: {e}"],
        ))


async def get_profit_loss(tool_input: Dict[str, Any]) -> str:
    """Fetch profit and loss statement for a period."""
    client = _get_client()

    try:
        filters = {
            "from_date": tool_input["from_date"],
            "to_date": tool_input["to_date"],
        }
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        result = await client.run_report("Profit and Loss Statement", filters)

        return json.dumps(audit_response(
            data=result.get("message", result),
            evidence_source="Profit and Loss Statement",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Profit and Loss Statement",
            confidence=Confidence.LOW,
            warnings=[f"Failed to generate P&L: {e}"],
        ))


async def get_cash_flow(tool_input: Dict[str, Any]) -> str:
    """Fetch cash flow statement for a period."""
    client = _get_client()

    try:
        filters = {
            "from_date": tool_input["from_date"],
            "to_date": tool_input["to_date"],
        }
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        result = await client.run_report("Cash Flow", filters)

        return json.dumps(audit_response(
            data=result.get("message", result),
            evidence_source="Cash Flow Statement",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Cash Flow Statement",
            confidence=Confidence.LOW,
            warnings=[f"Failed to generate cash flow statement: {e}"],
        ))


async def compare_financial_periods(tool_input: Dict[str, Any]) -> str:
    """Compare two financial periods and flag material variances."""
    client = _get_client()
    threshold = get_materiality_threshold()

    try:
        company_filter = {}
        if tool_input.get("company"):
            company_filter["company"] = tool_input["company"]

        # Fetch GL data for both periods
        p1_filters = {
            "from_date": tool_input["period1_start"],
            "to_date": tool_input["period1_end"],
            **company_filter,
        }
        p2_filters = {
            "from_date": tool_input["period2_start"],
            "to_date": tool_input["period2_end"],
            **company_filter,
        }

        p1 = await client.run_report("Trial Balance", p1_filters)
        p2 = await client.run_report("Trial Balance", p2_filters)

        p1_data = p1.get("message", p1) if isinstance(p1, dict) else p1
        p2_data = p2.get("message", p2) if isinstance(p2, dict) else p2

        # Build account-level comparison
        p1_rows = p1_data.get("result", []) if isinstance(p1_data, dict) else []
        p2_rows = p2_data.get("result", []) if isinstance(p2_data, dict) else []

        p1_balances = {}
        for row in p1_rows:
            if isinstance(row, dict) and row.get("account"):
                balance = float(row.get("debit", 0) or 0) - float(row.get("credit", 0) or 0)
                p1_balances[row["account"]] = balance

        p2_balances = {}
        for row in p2_rows:
            if isinstance(row, dict) and row.get("account"):
                balance = float(row.get("debit", 0) or 0) - float(row.get("credit", 0) or 0)
                p2_balances[row["account"]] = balance

        all_accounts = set(p1_balances.keys()) | set(p2_balances.keys())
        variances = []
        findings = []

        for account in sorted(all_accounts):
            b1 = p1_balances.get(account, 0)
            b2 = p2_balances.get(account, 0)
            variance = b2 - b1
            pct = (variance / b1 * 100) if b1 != 0 else (100.0 if b2 != 0 else 0.0)

            entry = {
                "account": account,
                "period1_balance": b1,
                "period2_balance": b2,
                "variance": variance,
                "variance_pct": round(pct, 2),
                "material": abs(variance) >= threshold,
            }
            variances.append(entry)

            if abs(variance) >= threshold:
                findings.append(AuditFinding(
                    title=f"Material variance in {account}",
                    risk_rating=RiskRating.MEDIUM if abs(pct) < 50 else RiskRating.HIGH,
                    assertions=[AuditAssertion.ACCURACY, AuditAssertion.COMPLETENESS],
                    observation=f"Account '{account}' changed by {variance:,.2f} ({pct:.1f}%) between periods.",
                    audit_reasoning="Material variance requires investigation to determine cause.",
                    impact=f"Variance of {variance:,.2f} exceeds materiality threshold of {threshold:,.2f}.",
                    recommendation="Investigate the cause of the material variance. Obtain management explanation and supporting evidence.",
                    confidence=Confidence.HIGH,
                ))

        return json.dumps(audit_response(
            data={
                "variances": variances,
                "material_variances": [v for v in variances if v["material"]],
                "total_accounts_compared": len(all_accounts),
                "materiality_threshold": threshold,
            },
            evidence_source="Trial Balance Comparison",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Trial Balance Comparison",
            confidence=Confidence.LOW,
            warnings=[f"Failed to compare periods: {e}"],
        ))
