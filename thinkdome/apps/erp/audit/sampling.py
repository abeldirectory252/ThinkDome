"""Audit sampling tools.

Tools: audit_random_sample, audit_high_value_sample,
       audit_risk_based_sample, audit_monetary_unit_sample
"""

from __future__ import annotations

import json
import logging
import random
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


async def random_sample(tool_input: Dict[str, Any]) -> str:
    """Select a simple random sample from a DocType population."""
    client = _get_client()
    doctype = tool_input["doctype"]
    sample_size = tool_input.get("sample_size", 25)

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list_all(
            doctype,
            filters=filters,
            fields=["name", "creation", "owner"],
        )

        if not records:
            return json.dumps(audit_response(
                data={"sample": [], "population_size": 0},
                evidence_source=doctype,
                confidence=Confidence.HIGH,
            ))

        sampled = random.sample(records, min(sample_size, len(records)))

        return json.dumps(audit_response(
            data={
                "sample": sampled,
                "sample_size": len(sampled),
                "population_size": len(records),
            },
            evidence_source=doctype,
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Sampling failed: {e}"],
        ))


async def high_value_sample(tool_input: Dict[str, Any]) -> str:
    """Select the highest-value items from the population."""
    client = _get_client()
    doctype = tool_input["doctype"]
    sample_size = tool_input.get("sample_size", 25)
    amount_field = tool_input.get("amount_field", "grand_total")

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list_all(
            doctype,
            filters=filters,
            fields=["name", amount_field, "creation", "owner"],
        )

        # Sort by value descending
        records.sort(key=lambda x: float(x.get(amount_field, 0) or 0), reverse=True)
        sampled = records[:sample_size]

        return json.dumps(audit_response(
            data={
                "sample": sampled,
                "sample_size": len(sampled),
                "population_size": len(records),
            },
            evidence_source=doctype,
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Sampling failed: {e}"],
        ))


async def risk_based_sample(tool_input: Dict[str, Any]) -> str:
    """Select a risk-weighted sample based on suspicious properties."""
    client = _get_client()
    doctype = tool_input["doctype"]
    sample_size = tool_input.get("sample_size", 25)
    amount_field = tool_input.get("amount_field", "grand_total")

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list_all(
            doctype,
            filters=filters,
            fields=["name", amount_field, "creation", "owner"],
        )

        weighted_records = []
        for r in records:
            # Score risk: starts with round amount, posted by admin, large value
            val = float(r.get(amount_field, 0) or 0)
            score = 1.0

            # Round number risk bonus
            if val > 0 and val == int(val) and val % 100 == 0:
                score += 3.0

            # Admin risk bonus
            if r.get("owner") in ("Administrator", "Administrator@example.com"):
                score += 2.0

            # Value weighting
            score += min(val / 10000.0, 5.0)

            weighted_records.append((score, r))

        # Sort by weight descending
        weighted_records.sort(key=lambda x: x[0], reverse=True)
        sampled = [item for weight, item in weighted_records[:sample_size]]

        return json.dumps(audit_response(
            data={
                "sample": sampled,
                "sample_size": len(sampled),
                "population_size": len(records),
            },
            evidence_source=doctype,
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Risk-based sampling failed: {e}"],
        ))


async def monetary_unit_sample(tool_input: Dict[str, Any]) -> str:
    """Select items using Probability Proportional to Size / Monetary Unit Sampling (MUS)."""
    client = _get_client()
    doctype = tool_input["doctype"]
    sample_size = tool_input.get("sample_size", 25)
    amount_field = tool_input.get("amount_field", "grand_total")

    try:
        filters: Dict[str, Any] = {}
        if tool_input.get("from_date") and tool_input.get("to_date"):
            filters["creation"] = ["between", [tool_input["from_date"], tool_input["to_date"]]]
        if tool_input.get("company"):
            filters["company"] = tool_input["company"]

        records = await client.get_list_all(
            doctype,
            filters=filters,
            fields=["name", amount_field, "creation"],
        )

        valid_records = [r for r in records if float(r.get(amount_field, 0) or 0) > 0]
        total_val = sum(float(r[amount_field]) for r in valid_records)

        if not valid_records or total_val <= 0:
            return json.dumps(audit_response(
                data={"sample": [], "population_size": len(records)},
                evidence_source=doctype,
                confidence=Confidence.HIGH,
            ))

        # Calculate sampling interval
        interval = total_val / sample_size

        # Order list (standard MUS orders by creation or ID)
        valid_records.sort(key=lambda x: x.get("creation", ""))

        sampled = []
        cumulative = 0.0
        # Select random starting point in first interval
        next_target = random.uniform(0, interval)

        for r in valid_records:
            val = float(r[amount_field])
            cumulative += val
            while cumulative >= next_target:
                sampled.append(r)
                next_target += interval
                if len(sampled) >= sample_size:
                    break
            if len(sampled) >= sample_size:
                break

        return json.dumps(audit_response(
            data={
                "sample": sampled,
                "sample_size": len(sampled),
                "population_size": len(records),
                "monetary_value": total_val,
                "sampling_interval": interval,
            },
            evidence_source=doctype,
            confidence=Confidence.HIGH,
        ), indent=2)
    except Exception as e:
        return json.dumps(audit_response(
            data=None, evidence_source=doctype,
            confidence=Confidence.LOW, warnings=[f"Monetary unit sampling failed: {e}"],
        ))
