"""Fraud analytics and forensic audit tools.

Tools: audit_detect_duplicate_transactions, audit_detect_duplicate_suppliers,
       audit_detect_duplicate_payments, audit_benford_analysis,
       audit_detect_round_amounts, audit_detect_unusual_users,
       audit_detect_after_hours_activity, audit_detect_management_override
"""

from __future__ import annotations

import json
import logging
import math
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
from thinkdome.apps.erp.audit.config import (
    get_thresholds,
    is_after_hours,
    is_weekend,
)

logger = logging.getLogger(__name__)

_client: AuditClient | None = None


def _get_client() -> AuditClient:
    global _client
    if _client is None:
        _client = AuditClient()
    return _client


async def detect_duplicate_transactions(tool_input: Dict[str, Any]) -> str:
    """Identify duplicate transaction entries across doctypes (e.g. Sales Invoices)."""
    client = _get_client()
    doctype = tool_input.get("doctype", "Sales Invoice")

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list(
            doctype,
            filters=filters,
            fields=["name", "posting_date", "grand_total", "owner", "creation"],
            limit_page_length=500,
        )

        duplicates = []
        for i, rec_a in enumerate(records):
            for rec_b in records[i + 1:]:
                # Check same amount, same date
                if (
                    rec_a.get("posting_date") == rec_b.get("posting_date")
                    and abs(float(rec_a.get("grand_total", 0) or 0) - float(rec_b.get("grand_total", 0) or 0)) < 0.01
                ):
                    duplicates.append({
                        "doc_a": rec_a["name"],
                        "doc_b": rec_b["name"],
                        "date": rec_a.get("posting_date"),
                        "amount": float(rec_a.get("grand_total", 0) or 0),
                        "owner_a": rec_a.get("owner"),
                        "owner_b": rec_b.get("owner"),
                    })

        return json.dumps(audit_response(
            data={"duplicates": duplicates, "count": len(duplicates)},
            evidence_source=doctype,
            confidence=Confidence.HIGH,
            warnings=[f"Identified {len(duplicates)} duplicate {doctype} records."] if duplicates else [],
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Duplicate transaction check failed: {e}"],
        ))


async def detect_duplicate_suppliers(tool_input: Dict[str, Any]) -> str:
    """Fuzzy match supplier names and details to detect duplicate suppliers."""
    client = _get_client()

    try:
        suppliers = await client.get_list(
            "Supplier",
            fields=["name", "supplier_name", "supplier_group", "creation", "owner"],
            limit_page_length=1000,
        )

        # Simple fuzzy/substring matching
        duplicates = []
        for i, s1 in enumerate(suppliers):
            name1 = str(s1.get("supplier_name", "")).strip().lower()
            if not name1:
                continue
            for s2 in suppliers[i + 1:]:
                name2 = str(s2.get("supplier_name", "")).strip().lower()
                if not name2:
                    continue
                # If identical or highly similar (e.g. one starts with another)
                if name1 == name2 or (len(name1) > 4 and len(name2) > 4 and (name1 in name2 or name2 in name1)):
                    duplicates.append({
                        "supplier_a": s1["name"],
                        "supplier_name_a": s1["supplier_name"],
                        "supplier_b": s2["name"],
                        "supplier_name_b": s2["supplier_name"],
                    })

        findings = []
        if duplicates:
            findings.append(AuditFinding(
                title="Duplicate Suppliers Identified",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.RIGHTS_AND_OBLIGATIONS, AuditAssertion.EXISTENCE],
                observation=f"Detected {len(duplicates)} potential duplicate supplier records.",
                audit_reasoning="Duplicate suppliers are a high risk for billing schemes, duplicate payments, or kickback schemes.",
                recommendation="Investigate the vendor database, merge duplicate records, and check payments associated with these suppliers.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={"duplicate_suppliers": duplicates, "count": len(duplicates)},
            evidence_source="Supplier",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Supplier",
            confidence=Confidence.LOW, warnings=[f"Failed to check duplicate suppliers: {e}"],
        ))


async def detect_duplicate_payments(tool_input: Dict[str, Any]) -> str:
    """Find payments with identical details (reuses banking duplicate checker logic)."""
    from thinkdome.apps.erp.audit.banking import find_duplicate_payments as fdp
    return await fdp(tool_input)


async def benford_analysis(tool_input: Dict[str, Any]) -> str:
    """Perform Benford's Law first-digit distribution check on transaction amounts."""
    client = _get_client()
    doctype = tool_input["doctype"]
    amount_field = tool_input.get("amount_field", "grand_total")
    chi_critical = get_thresholds().get("benford_chi_squared_critical", 15.507)

    try:
        filters: Dict[str, Any] = {"docstatus": 1}
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list(
            doctype,
            filters=filters,
            fields=["name", amount_field],
            limit_page_length=1000,
        )

        first_digits = [0] * 10
        total_count = 0

        for r in records:
            val = float(r.get(amount_field, 0) or 0)
            if val > 0:
                # Find first non-zero digit
                digit_str = str(val).lstrip("0.-")
                if digit_str and digit_str[0].isdigit():
                    digit = int(digit_str[0])
                    if 1 <= digit <= 9:
                        first_digits[digit] += 1
                        total_count += 1

        if total_count < 50:
            return json.dumps(audit_response(
                data=None, evidence_source=doctype,
                confidence=Confidence.LOW,
                warnings=[f"Insufficient sample size ({total_count} records). Benford's Law analysis requires at least 50 non-zero values."],
            ))

        # Expected Benford probabilities
        expected_probs = [0.0, 0.301, 0.176, 0.125, 0.097, 0.079, 0.067, 0.058, 0.051, 0.046]
        actual_dist = [0.0] * 10
        chi_square = 0.0

        for d in range(1, 10):
            actual_dist[d] = round(first_digits[d] / total_count, 3)
            expected_count = total_count * expected_probs[d]
            chi_square += ((first_digits[d] - expected_count) ** 2) / expected_count

        anomaly_detected = chi_square > chi_critical
        findings = []
        if anomaly_detected:
            findings.append(AuditFinding(
                title=f"Benford Distribution Anomaly on {doctype}",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.ACCURACY, AuditAssertion.EXISTENCE],
                observation=f"Benford first-digit distribution check failed for {doctype}. Chi-Square: {chi_square:.2f} (Critical: {chi_critical})",
                audit_reasoning="Fictitious or fabricated transaction amounts tend to follow human digit preferences rather than Benford's Law.",
                recommendation="Perform details testing and sample validation on transactions starting with digits that exceed expected ranges.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data={
                "total_records_analyzed": total_count,
                "chi_square_statistic": chi_square,
                "critical_value": chi_critical,
                "anomaly_detected": anomaly_detected,
                "distribution": {
                    str(d): {"actual": actual_dist[d], "expected": expected_probs[d], "count": first_digits[d]}
                    for d in range(1, 10)
                }
            },
            evidence_source=doctype,
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Benford analysis failed: {e}"],
        ))


async def detect_round_amounts(tool_input: Dict[str, Any]) -> str:
    """Find round-number transactions across any DocType (shortcut/wrapper for ledger find_round_number_entries)."""
    from thinkdome.apps.erp.audit.ledger import find_round_number_entries as frne
    return await frne(tool_input)


async def detect_unusual_users(tool_input: Dict[str, Any]) -> str:
    """Analyze activity levels per user to find outliers, suspicious usage, or compromised profile actions."""
    client = _get_client()

    try:
        # Aggregate logs by user in Activity Log
        logs = await client.get_list(
            "Activity Log",
            fields=["user", "operation", "status"],
            limit_page_length=1000,
        )

        user_activity: Dict[str, Dict] = {}
        for l in logs:
            usr = l.get("user")
            if usr:
                if usr not in user_activity:
                    user_activity[usr] = {"total_actions": 0, "failed_logins": 0}
                user_activity[usr]["total_actions"] += 1
                if l.get("operation") == "Login" and l.get("status") == "Failed":
                    user_activity[usr]["failed_logins"] += 1

        # Check for admin or system manager activity
        warnings = []
        for usr, stats in user_activity.items():
            if stats["failed_logins"] > 10:
                warnings.append(f"User '{usr}' has high count of failed login attempts: {stats['failed_logins']}")

        return json.dumps(audit_response(
            data={"user_activity": user_activity, "count": len(user_activity)},
            evidence_source="Activity Log",
            confidence=Confidence.HIGH,
            warnings=warnings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Activity Log",
            confidence=Confidence.LOW, warnings=[f"Unusual users analysis failed: {e}"],
        ))


async def detect_after_hours_activity(tool_input: Dict[str, Any]) -> str:
    """Find entries created outside standard business hours or on weekends."""
    from thinkdome.apps.erp.audit.ledger import find_weekend_postings as fwp
    return await fwp(tool_input)


async def detect_management_override(tool_input: Dict[str, Any]) -> str:
    """Identify direct administrator database postings, workflow bypasses, or limit overrides."""
    client = _get_client()

    try:
        # Administrators posting journal entries or invoices
        admin_filters: Dict[str, Any] = {
            "owner": ["in", ["Administrator", "Administrator@example.com"]],
            "docstatus": 1
        }
        if tool_input.get("company"):
            admin_filters["company"] = tool_input["company"]

        admin_journals = await client.get_list(
            "Journal Entry",
            filters=admin_filters,
            fields=["name", "posting_date", "grand_total", "owner", "creation"],
            limit_page_length=100,
        )

        admin_invoices = await client.get_list(
            "Sales Invoice",
            filters=admin_filters,
            fields=["name", "posting_date", "grand_total", "owner", "creation"],
            limit_page_length=100,
        )

        overrides = {
            "admin_journal_entries": admin_journals,
            "admin_sales_invoices": admin_invoices,
            "total_count": len(admin_journals) + len(admin_invoices),
        }

        findings = []
        if overrides["total_count"] > 0:
            findings.append(AuditFinding(
                title="Management Override Activity Detected",
                risk_rating=RiskRating.HIGH,
                assertions=[AuditAssertion.OCCURRENCE, AuditAssertion.RIGHTS_AND_OBLIGATIONS],
                observation=f"Privileged Administrator account posted {len(admin_journals)} JEs and {len(admin_invoices)} invoices directly.",
                audit_reasoning="Direct transaction postings by administrators bypass workflow segregation controls and indicate management override risks.",
                recommendation="Investigate why administrator logins were used for standard posting tasks. Restrict admin postings.",
                confidence=Confidence.HIGH,
            ))

        return json.dumps(audit_response(
            data=overrides,
            evidence_source="Journal Entry / Sales Invoice",
            confidence=Confidence.HIGH,
            findings=findings,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source="Journal Entry",
            confidence=Confidence.LOW, warnings=[f"Management override check failed: {e}"],
        ))
