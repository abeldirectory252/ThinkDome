"""Unit tests for read-only AuditClient wrapper."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from thinkdome.apps.erp.frappe_client import FrappeClient
from thinkdome.apps.erp.audit.client import AuditClient, WriteBlockedError


@pytest.fixture
def mock_frappe_client():
    client = MagicMock(spec=FrappeClient)
    client.is_connected = True
    client.is_configured = True
    client.get_doc = AsyncMock(return_value={"name": "test_doc", "owner": "admin"})
    client.get_list = AsyncMock(return_value=[{"name": "test_doc"}])
    return client


@pytest.mark.asyncio
async def test_write_operations_blocked(mock_frappe_client):
    """Test that all modify operations raise WriteBlockedError."""
    audit_client = AuditClient(frappe_client=mock_frappe_client)

    with pytest.raises(WriteBlockedError):
        await audit_client.create_doc("Journal Entry", {"name": "test"})

    with pytest.raises(WriteBlockedError):
        await audit_client.update_doc("Journal Entry", "JE-001", {"remarks": "edit"})

    with pytest.raises(WriteBlockedError):
        await audit_client.delete_doc("Journal Entry", "JE-001")


@pytest.mark.asyncio
async def test_cache_hits(mock_frappe_client):
    """Test that consecutive get_doc calls hit the cache."""
    audit_client = AuditClient(frappe_client=mock_frappe_client)

    # First call: cache miss
    doc1 = await audit_client.get_doc("Journal Entry", "JE-001")
    assert mock_frappe_client.get_doc.call_count == 1
    assert doc1 == {"name": "test_doc", "owner": "admin"}

    # Second call: cache hit
    doc2 = await audit_client.get_doc("Journal Entry", "JE-001")
    assert mock_frappe_client.get_doc.call_count == 1
    assert doc2 == {"name": "test_doc", "owner": "admin"}


def test_trace_id_generation():
    """Test unique trace ID generation per audit session."""
    audit_client = AuditClient()
    trace1 = audit_client.trace_id
    assert trace1.startswith("AUDIT-")

    trace2 = audit_client.new_trace()
    assert trace2 != trace1
