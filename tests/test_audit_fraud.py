"""Unit tests for Fraud Analytics audit tools."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from thinkdome.apps.erp.audit import fraud
from thinkdome.apps.erp.audit.types import RiskRating


@pytest.mark.asyncio
@patch("thinkdome.apps.erp.audit.fraud._get_client")
async def test_detect_duplicate_suppliers(mock_get_client):
    """Test duplicate supplier detection with fuzzy matching names."""
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    # Set mock list of suppliers
    mock_client.get_list.return_value = [
        {"name": "SUP-001", "supplier_name": "Acme Corp"},
        {"name": "SUP-002", "supplier_name": "Acme Corporation"},
        {"name": "SUP-003", "supplier_name": "Global Trade"},
    ]

    res_str = await fraud.detect_duplicate_suppliers({})
    res = json.loads(res_str)

    assert "data" in res
    assert len(res["data"]["duplicate_suppliers"]) == 1
    assert res["data"]["duplicate_suppliers"][0]["supplier_a"] == "SUP-001"
    assert res["data"]["duplicate_suppliers"][0]["supplier_b"] == "SUP-002"
    assert len(res["findings"]) == 1
    assert res["findings"][0]["risk_rating"] == "HIGH"


@pytest.mark.asyncio
@patch("thinkdome.apps.erp.audit.fraud._get_client")
async def test_benford_analysis(mock_get_client):
    """Test Benford's Law distribution analysis and anomaly flags."""
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    # Populate 100 entries starting with 9 (highly anomalous, Benford expects 4.6%)
    records = []
    for i in range(100):
        records.append({"name": f"INV-{i}", "grand_total": 900.0})

    mock_client.get_list.return_value = records

    res_str = await fraud.benford_analysis({"doctype": "Sales Invoice", "amount_field": "grand_total"})
    res = json.loads(res_str)

    assert res["data"]["anomaly_detected"] is True
    assert res["findings"][0]["risk_rating"] == "HIGH"
