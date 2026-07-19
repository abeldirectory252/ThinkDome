"""Company information audit tools.

Tools: audit_get_company, audit_get_chart_of_accounts, audit_get_accounting_periods
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from thinkdome.apps.erp.audit.client import AuditClient
from thinkdome.apps.erp.audit.types import (
    AuditEvidence,
    Confidence,
    CompanyInput,
    EmptyInput,
    audit_response,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def get_company(tool_input: Dict[str, Any]) -> str:
    """Fetch company information, fiscal year settings, and basic configuration."""
    client = _get_client()
    company = tool_input.get("company")
    warnings = []

    try:
        if company:
            data = await client.get_doc("Company", company)
        else:
            # Get default company
            companies = await client.get_list(
                "Company",
                fields=["name", "company_name", "default_currency", "country",
                        "creation", "modified", "owner"],
                limit_page_length=10,
            )
            if not companies:
                return json.dumps(audit_response(
                    data=None,
                    evidence_source="Company",
                    confidence=Confidence.LOW,
                    warnings=["No companies found in ERPNext. Unable to proceed with audit."],
                ))
            data = companies[0]
            if len(companies) > 1:
                warnings.append(f"Multiple companies found ({len(companies)}). Returning first. Specify company name for others.")

        return json.dumps(audit_response(
            data=data,
            evidence_source="Company",
            confidence=Confidence.HIGH,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Company",
            confidence=Confidence.LOW,
            warnings=[f"Failed to fetch company data: {e}"],
        ))


async def get_chart_of_accounts(tool_input: Dict[str, Any]) -> str:
    """Fetch the full Chart of Accounts hierarchy with account types and classifications."""
    client = _get_client()
    company = tool_input.get("company")

    try:
        filters = {}
        if company:
            filters["company"] = company

        accounts = await client.get_list_all(
            "Account",
            filters=filters,
            fields=[
                "name", "account_name", "account_type", "root_type",
                "parent_account", "is_group", "company", "balance_must_be",
                "account_currency", "creation", "modified",
            ],
            order_by="lft asc",
            max_records=2000,
        )

        # Classify accounts for audit purposes
        summary = {
            "total_accounts": len(accounts),
            "by_root_type": {},
            "by_account_type": {},
            "group_accounts": 0,
            "leaf_accounts": 0,
        }
        for acc in accounts:
            rt = acc.get("root_type", "Unknown")
            at = acc.get("account_type", "None")
            summary["by_root_type"][rt] = summary["by_root_type"].get(rt, 0) + 1
            summary["by_account_type"][at] = summary["by_account_type"].get(at, 0) + 1
            if acc.get("is_group"):
                summary["group_accounts"] += 1
            else:
                summary["leaf_accounts"] += 1

        return json.dumps(audit_response(
            data={"accounts": accounts, "summary": summary},
            evidence_source="Account",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Account",
            confidence=Confidence.LOW,
            warnings=[f"Failed to fetch chart of accounts: {e}"],
        ))


async def get_accounting_periods(tool_input: Dict[str, Any]) -> str:
    """Fetch fiscal years and accounting period closing status."""
    client = _get_client()
    company = tool_input.get("company")

    try:
        # Fiscal Years
        fy_filters = {}
        if company:
            fy_filters["company"] = company

        fiscal_years = await client.get_list(
            "Fiscal Year",
            filters=fy_filters,
            fields=["name", "year_start_date", "year_end_date", "disabled",
                    "creation", "modified", "owner"],
            order_by="year_start_date desc",
            limit_page_length=20,
        )

        # Period Closing Vouchers
        closings = await client.get_list(
            "Period Closing Voucher",
            filters=fy_filters if company else None,
            fields=["name", "posting_date", "fiscal_year", "company",
                    "closing_account_head", "docstatus", "creation", "owner"],
            order_by="posting_date desc",
            limit_page_length=50,
        )

        warnings = []
        # Check for open fiscal years that should be closed
        for fy in fiscal_years:
            if not fy.get("disabled"):
                has_closing = any(
                    c.get("fiscal_year") == fy.get("name") and c.get("docstatus") == 1
                    for c in closings
                )
                if not has_closing:
                    warnings.append(
                        f"Fiscal Year '{fy.get('name')}' is active but has no submitted Period Closing Voucher."
                    )

        return json.dumps(audit_response(
            data={
                "fiscal_years": fiscal_years,
                "period_closings": closings,
            },
            evidence_source="Fiscal Year / Period Closing Voucher",
            confidence=Confidence.HIGH,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None,
            evidence_source="Fiscal Year",
            confidence=Confidence.LOW,
            warnings=[f"Failed to fetch accounting periods: {e}"],
        ))
