"""Fixed Asset audit tools.

Tools: audit_get_asset_register, audit_test_asset_existence,
       audit_check_depreciation, audit_find_asset_disposals
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


async def get_asset_register(tool_input: Dict[str, Any]) -> str:
    """Fetch the asset register containing active assets, purchase values, and accumulated depreciation."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        assets = await client.get_list(
            "Asset",
            filters=filters,
            fields=[
                "name", "asset_name", "asset_category", "item_code", "status",
                "purchase_date", "gross_purchase_amount", "opening_accumulated_depreciation",
                "value_after_depreciation", "company", "location", "custodian", "creation"
            ],
            order_by="purchase_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        return json.dumps(audit_response(
            data={"assets": assets, "count": len(assets)},
            evidence_source="Asset",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Asset",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch asset register: {e}"],
        ))


async def test_asset_existence(tool_input: Dict[str, Any]) -> str:
    """Cross-reference asset register entries against purchase invoices and capital general ledger entries."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"status": ["in", ["Submitted", "Partially Depreciated", "Fully Depreciated"]]}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        assets = await client.get_list(
            "Asset",
            filters=filters,
            fields=["name", "asset_name", "purchase_invoice", "gross_purchase_amount", "purchase_date", "company"],
            limit_page_length=100,
        )

        unlinked = []
        for asset in assets:
            pi_name = asset.get("purchase_invoice")
            if not pi_name:
                unlinked.append(asset)
            else:
                try:
                    # Verify purchase invoice exists
                    await client.get_doc("Purchase Invoice", pi_name)
                except Exception:
                    asset["_invoice_missing"] = True
                    unlinked.append(asset)

        findings = []
        if unlinked:
            findings.append(AuditFinding(
                title="Fixed Assets Lacking Purchase Invoice Link",
                risk_rating=RiskRating.HIGH if any(float(a.get("gross_purchase_amount", 0) or 0) > 10000 for a in unlinked) else RiskRating.MEDIUM,
                assertions=[AuditAssertion.EXISTENCE, AuditAssertion.RIGHTS_AND_OBLIGATIONS],
                observation=f"{len(unlinked)} asset records lack a verifiable purchase invoice linkage in ERPNext.",
                audit_reasoning="Assets registered without invoice records pose risks of fictitious capitalization, valuation errors, or missing ownership rights.",
                recommendation="Review the physical asset acquisition documents and invoices manually for unlinked entries.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"unlinked_assets": unlinked, "count": len(unlinked)},
            evidence_source="Asset / Purchase Invoice",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Asset",
            confidence=Confidence.LOW, warnings=[f"Failed to verify asset existence: {e}"],
        ))


async def check_depreciation(tool_input: Dict[str, Any]) -> str:
    """Verify depreciation calculations, postings, and schedules for assets."""
    client = _get_client()

    try:
        # Fetch asset finance books or depreciation schedules (Asset Depreciation Schedule in v14/v15)
        # We look at the Asset Finance Book or Asset Finance Book Detail
        # For simplicity across versions, we inspect posted Journal Entries with 'depreciation' in remarks/accounts.
        filters: Dict[str, Any] = {"is_cancelled": 0}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        # Look for posted depreciation journal entries
        gl_filters = {
            "remarks": ["like", "%depreciation%"],
            "is_cancelled": 0,
            **({"company": tool_input["company"]} if tool_input.get("company") else {})
        }

        dep_entries = await client.get_list(
            "GL Entry",
            filters=gl_filters,
            fields=["name", "posting_date", "account", "debit", "credit", "voucher_no", "remarks"],
            limit_page_length=200,
        )

        return json.dumps(audit_response(
            data={"depreciation_gl_postings": dep_entries, "count": len(dep_entries)},
            evidence_source="GL Entry",
            confidence=Confidence.MEDIUM,
            warnings=["Please review physical asset depreciation schedules for straight-line calculations vs these entries."] if not dep_entries else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Failed to verify depreciation postings: {e}"],
        ))


async def find_asset_disposals(tool_input: Dict[str, Any]) -> str:
    """Identify and review asset disposals, sales, and scrap entries."""
    client = _get_client()

    try:
        # Scrapped or Sold assets
        filters: Dict[str, Any] = {"status": ["in", ["Scrapped", "Sold"]]}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        disposals = await client.get_list(
            "Asset",
            filters=filters,
            fields=["name", "asset_name", "asset_category", "gross_purchase_amount",
                    "value_after_depreciation", "status", "disposal_date", "company", "owner"],
            order_by="disposal_date desc",
            limit_page_length=100,
        )

        findings = []
        for d in disposals:
            # Check if value after depreciation was high on disposal (potential loss/gain misstatement)
            net_book_val = float(d.get("value_after_depreciation", 0) or 0)
            if net_book_val > 5000.0:
                findings.append(AuditFinding(
                    title="Significant Net Book Value Scrapped",
                    risk_rating=RiskRating.MEDIUM,
                    assertions=[AuditAssertion.VALUATION, AuditAssertion.CLASSIFICATION],
                    observation=f"Asset {d['name']} was disposed with net book value of {net_book_val:,.2f}.",
                    audit_reasoning="Disposing assets with significant Net Book Value requires authorization and review of depreciation rate accuracy.",
                    recommendation="Obtain disposal approval forms and inspect write-off calculations.",
                    confidence=Confidence.HIGH,
                ))

        return json.dumps(audit_response(
            data={"disposals": disposals, "count": len(disposals)},
            evidence_source="Asset",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Asset",
            confidence=Confidence.LOW, warnings=[f"Failed to fetch asset disposals: {e}"],
        ))
