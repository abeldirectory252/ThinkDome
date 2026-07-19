"""Unit tests for Audit Sampling tools."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from thinkdome.apps.erp.audit import sampling


@pytest.mark.asyncio
@patch("thinkdome.apps.erp.audit.sampling._get_client")
async def test_monetary_unit_sampling(mock_get_client):
    """Test Monetary Unit Sampling (MUS) probability proportional to size logic."""
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    # Define population with one high-value item and many small items
    records = [
        {"name": "INV-001", "grand_total": 50000.0, "creation": "2026-01-01"},
    ]
    for i in range(100):
        records.append({"name": f"INV-small-{i}", "grand_total": 10.0, "creation": "2026-01-02"})

    mock_client.get_list_all.return_value = records

    # Select 5 samples. Due to high value, INV-001 MUST be selected in MUS
    res_str = await sampling.monetary_unit_sample({
        "doctype": "Sales Invoice",
        "sample_size": 5,
        "amount_field": "grand_total",
    })
    res = json.loads(res_str)

    assert len(res["data"]["sample"]) == 5
    # The high value invoice must be present in the sample
    sample_names = [item["name"] for item in res["data"]["sample"]]
    assert "INV-001" in sample_names


@pytest.mark.asyncio
@patch("thinkdome.apps.erp.audit.sampling._get_client")
async def test_high_value_sampling(mock_get_client):
    """Test high-value sampling sorting order."""
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    records = [
        {"name": "INV-low", "grand_total": 10.0},
        {"name": "INV-high", "grand_total": 10000.0},
        {"name": "INV-mid", "grand_total": 500.0},
    ]
    mock_client.get_list_all.return_value = records

    res_str = await sampling.high_value_sample({
        "doctype": "Sales Invoice",
        "sample_size": 2,
        "amount_field": "grand_total",
    })
    res = json.loads(res_str)

    assert len(res["data"]["sample"]) == 2
    assert res["data"]["sample"][0]["name"] == "INV-high"
    assert res["data"]["sample"][1]["name"] == "INV-mid"
