"""General ledger audit tools.

Tools: audit_search_general_ledger, audit_find_large_transactions,
       audit_find_manual_journals, audit_find_backdated_entries,
       audit_find_year_end_entries, audit_find_round_number_entries,
       audit_find_weekend_postings
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
from thinkdome.apps.erp.audit.config import (
    get_materiality_threshold,
    get_thresholds,
    get_weekend_days,
    is_weekend,
    is_after_hours,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None

GL_FIELDS = [
    "name", "posting_date", "account", "party_type", "party",
    "debit", "credit", "voucher_type", "voucher_no",
    "cost_center", "remarks", "is_cancelled",
    "creation", "modified", "owner",
]


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


def _build_gl_filters(tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """Build GL Entry filters from tool input."""
    filters: Dict[str, Any] = {"is_cancelled": 0}
    if tool_input.get("from_date"):
        filters["posting_date"] = [">=", tool_input["from_date"]]
    if tool_input.get("to_date"):
        if "posting_date" in filters:
            filters["posting_date"] = ["between", [tool_input.get("from_date", "2000-01-01"), tool_input["to_date"]]]
        else:
            filters["posting_date"] = ["<=", tool_input["to_date"]]
    if tool_input.get("account"):
        filters["account"] = tool_input["account"]
    if tool_input.get("party"):
        filters["party"] = tool_input["party"]
    if tool_input.get("voucher_type"):
        filters["voucher_type"] = tool_input["voucher_type"]
    if tool_input.get("company"):
        filters["company"] = tool_input["company"]
    return filters


async def search_general_ledger(tool_input: Dict[str, Any]) -> str:
    """Search the general ledger with flexible filters."""
    client = _get_client()

    try:
        filters = _build_gl_filters(tool_input)

        # Amount range filter requires post-fetch filtering since GL uses debit/credit
        min_amount = tool_input.get("min_amount")
        max_amount = tool_input.get("max_amount")

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="posting_date desc, creation desc",
            limit_page_length=tool_input.get("limit", 500),
        )

        # Post-filter by amount if specified
        if min_amount is not None or max_amount is not None:
            filtered = []
            for e in entries:
                amount = max(float(e.get("debit", 0) or 0), float(e.get("credit", 0) or 0))
                if min_amount is not None and amount < min_amount:
                    continue
                if max_amount is not None and amount > max_amount:
                    continue
                filtered.append(e)
            entries = filtered

        return json.dumps(audit_response(
            data={"entries": entries, "count": len(entries)},
            evidence_source="GL Entry",
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"GL search failed: {e}"],
        ))


async def find_large_transactions(tool_input: Dict[str, Any]) -> str:
    """Find transactions exceeding the materiality threshold."""
    client = _get_client()
    threshold = tool_input.get("threshold") or get_materiality_threshold()

    try:
        filters = _build_gl_filters(tool_input)

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        large = []
        for e in entries:
            amount = max(float(e.get("debit", 0) or 0), float(e.get("credit", 0) or 0))
            if amount >= threshold:
                e["_amount"] = amount
                large.append(e)

        large.sort(key=lambda x: x["_amount"], reverse=True)

        return json.dumps(audit_response(
            data={
                "entries": large,
                "count": len(large),
                "threshold": threshold,
            },
            evidence_source="GL Entry",
            confidence=Confidence.HIGH,
            warnings=[f"Found {len(large)} transactions >= {threshold:,.2f}"] if large else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Large transaction search failed: {e}"],
        ))


async def find_manual_journals(tool_input: Dict[str, Any]) -> str:
    """Find manually created journal entries (not from automated workflows)."""
    client = _get_client()

    try:
        filters: Dict[str, Any] = {"is_cancelled": 0, "voucher_type": "Journal Entry"}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["posting_date"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        # Group by voucher_no to get unique journal entries
        journals: Dict[str, Dict] = {}
        for e in entries:
            vn = e.get("voucher_no", "")
            if vn not in journals:
                journals[vn] = {
                    "voucher_no": vn,
                    "posting_date": e.get("posting_date"),
                    "owner": e.get("owner"),
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "line_count": 0,
                    "remarks": e.get("remarks", ""),
                }
            journals[vn]["total_debit"] += float(e.get("debit", 0) or 0)
            journals[vn]["total_credit"] += float(e.get("credit", 0) or 0)
            journals[vn]["line_count"] += 1

        journal_list = sorted(journals.values(), key=lambda x: x["total_debit"], reverse=True)

        return json.dumps(audit_response(
            data={"manual_journals": journal_list, "count": len(journal_list)},
            evidence_source="GL Entry (voucher_type=Journal Entry)",
            confidence=Confidence.HIGH,
            warnings=[
                f"Found {len(journal_list)} manual journal entries. "
                "Manual journals carry higher fraud risk and require substantive testing."
            ] if journal_list else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Manual journal search failed: {e}"],
        ))


async def find_backdated_entries(tool_input: Dict[str, Any]) -> str:
    """Find entries where posting_date is significantly before creation date."""
    client = _get_client()
    backdated_days = get_thresholds().get("backdated_entry_days", 30)

    try:
        filters = _build_gl_filters(tool_input)

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="creation desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        backdated = []
        for e in entries:
            posting = e.get("posting_date", "")
            creation = e.get("creation", "")
            if posting and creation:
                try:
                    post_dt = datetime.strptime(str(posting)[:10], "%Y-%m-%d").date()
                    create_dt = datetime.strptime(str(creation)[:10], "%Y-%m-%d").date()
                    gap_days = (create_dt - post_dt).days
                    if gap_days >= backdated_days:
                        e["_gap_days"] = gap_days
                        backdated.append(e)
                except (ValueError, TypeError):
                    continue

        backdated.sort(key=lambda x: x.get("_gap_days", 0), reverse=True)

        findings = []
        if backdated:
            findings.append(AuditFinding(
                title="Backdated GL Entries Detected",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.CUTOFF, AuditAssertion.OCCURRENCE],
                observation=f"{len(backdated)} entries have posting dates {backdated_days}+ days before creation.",
                audit_reasoning="Backdated entries may indicate management override, period manipulation, or fraudulent recording.",
                impact="Financial statements may be misstated due to entries recorded in incorrect periods.",
                recommendation="Investigate each backdated entry. Verify business justification and authorization.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"backdated_entries": backdated, "count": len(backdated), "threshold_days": backdated_days},
            evidence_source="GL Entry",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Backdated entry search failed: {e}"],
        ))


async def find_year_end_entries(tool_input: Dict[str, Any]) -> str:
    """Find entries posted in the last N days of a fiscal year."""
    client = _get_client()
    year_end_days = get_thresholds().get("year_end_days", 15)

    try:
        # Get fiscal years to determine year-end dates
        fy_filters = {}
        if tool_input.get("company"):
            fy_filters["company"] = tool_input["company"]

        fiscal_years = await client.get_list(
            "Fiscal Year",
            filters=fy_filters,
            fields=["name", "year_end_date"],
            order_by="year_end_date desc",
            limit_page_length=5,
        )

        all_year_end_entries = []
        for fy in fiscal_years:
            end_date_str = str(fy.get("year_end_date", ""))[:10]
            if not end_date_str:
                continue
            try:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                from datetime import timedelta
                start_window = end_date - timedelta(days=year_end_days)

                entries = await client.get_list(
                    "GL Entry",
                    filters={
                        "posting_date": ["between", [start_window.isoformat(), end_date.isoformat()]],
                        "is_cancelled": 0,
                        **({"company": tool_input["company"]} if tool_input.get("company") else {}),
                    },
                    fields=GL_FIELDS,
                    order_by="posting_date desc",
                    limit_page_length=200,
                )

                for e in entries:
                    e["_fiscal_year"] = fy.get("name")
                    e["_year_end_date"] = end_date_str
                all_year_end_entries.extend(entries)
            except (ValueError, TypeError):
                continue

        return json.dumps(audit_response(
            data={
                "year_end_entries": all_year_end_entries,
                "count": len(all_year_end_entries),
                "window_days": year_end_days,
            },
            evidence_source="GL Entry / Fiscal Year",
            confidence=Confidence.HIGH,
            warnings=[
                f"Found {len(all_year_end_entries)} entries in year-end windows. "
                "Year-end adjustments carry elevated risk of management override."
            ] if all_year_end_entries else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Year-end entry search failed: {e}"],
        ))


async def find_round_number_entries(tool_input: Dict[str, Any]) -> str:
    """Find entries with suspiciously round amounts."""
    client = _get_client()
    round_threshold = tool_input.get("threshold") or get_materiality_threshold()

    try:
        filters = _build_gl_filters(tool_input)

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        round_entries = []
        for e in entries:
            for field in ("debit", "credit"):
                amount = float(e.get(field, 0) or 0)
                if amount >= round_threshold and amount == int(amount) and amount % 100 == 0:
                    e["_round_amount"] = amount
                    e["_round_field"] = field
                    round_entries.append(e)
                    break

        return json.dumps(audit_response(
            data={
                "round_entries": round_entries,
                "count": len(round_entries),
                "threshold": round_threshold,
            },
            evidence_source="GL Entry",
            confidence=Confidence.MEDIUM,
            warnings=[
                f"Found {len(round_entries)} round-number entries >= {round_threshold:,.0f}. "
                "Round numbers may indicate estimates, fabrication, or lack of supporting documentation."
            ] if round_entries else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Round number search failed: {e}"],
        ))


async def find_weekend_postings(tool_input: Dict[str, Any]) -> str:
    """Find entries posted on weekends or outside business hours."""
    client = _get_client()
    weekend_days = get_weekend_days()

    try:
        filters = _build_gl_filters(tool_input)

        entries = await client.get_list(
            "GL Entry",
            filters=filters,
            fields=GL_FIELDS,
            order_by="posting_date desc",
            limit_page_length=tool_input.get("limit", 200),
        )

        weekend_entries = []
        after_hours_entries = []

        for e in entries:
            posting = e.get("posting_date", "")
            creation = e.get("creation", "")
            if posting:
                try:
                    post_dt = datetime.strptime(str(posting)[:10], "%Y-%m-%d")
                    if post_dt.weekday() in weekend_days:
                        e["_posting_weekday"] = post_dt.strftime("%A")
                        weekend_entries.append(e)
                except (ValueError, TypeError):
                    pass

            if creation:
                try:
                    create_dt = datetime.strptime(str(creation)[:19], "%Y-%m-%d %H:%M:%S")
                    if is_after_hours(create_dt.hour, create_dt.minute):
                        e["_creation_time"] = create_dt.strftime("%H:%M:%S")
                        after_hours_entries.append(e)
                except (ValueError, TypeError):
                    pass

        return json.dumps(audit_response(
            data={
                "weekend_entries": weekend_entries,
                "weekend_count": len(weekend_entries),
                "after_hours_entries": after_hours_entries,
                "after_hours_count": len(after_hours_entries),
            },
            evidence_source="GL Entry",
            confidence=Confidence.HIGH,
            warnings=[
                f"Found {len(weekend_entries)} weekend postings and {len(after_hours_entries)} after-hours entries. "
                "Activity outside normal business hours may indicate unauthorized access."
            ] if (weekend_entries or after_hours_entries) else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="GL Entry",
            confidence=Confidence.LOW, warnings=[f"Weekend posting search failed: {e}"],
        ))
