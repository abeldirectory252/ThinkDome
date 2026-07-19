"""Unit tests for Segregation of Duties conflicts analysis."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from thinkdome.apps.erp.audit import permissions


@pytest.mark.asyncio
@patch("thinkdome.apps.erp.audit.permissions._get_client")
async def test_sod_conflict_detection(mock_get_client):
    """Test identifying Segregation of Duties conflicts on users with overlapping roles."""
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client

    # Define users: one conflict, one safe
    mock_client.get_list.side_effect = [
        # First call: users
        [
            {"name": "conflict@example.com", "email": "conflict@example.com"},
            {"name": "safe@example.com", "email": "safe@example.com"},
        ],
        # Second call: Has Role links
        [
            {"parent": "conflict@example.com", "role": "Purchase User"},
            {"parent": "conflict@example.com", "role": "Accounts User"},
            {"parent": "safe@example.com", "role": "Purchase User"},
        ]
    ]

    res_str = await permissions.check_sod_conflicts({})
    res = json.loads(res_str)

    assert len(res["data"]["conflicts"]) == 1
    conflict = res["data"]["conflicts"][0]
    assert conflict["user"] == "conflict@example.com"
    assert conflict["role_a"] == "Purchase User"
    assert conflict["role_b"] == "Accounts User"
    assert len(res["findings"]) == 1
    assert res["findings"][0]["risk_rating"] == "HIGH"
