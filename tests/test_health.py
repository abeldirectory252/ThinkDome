"""Health endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness(client):
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data