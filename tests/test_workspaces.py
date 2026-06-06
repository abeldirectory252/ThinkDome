"""Workspace endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_workspace_lifecycle(client):
    # Create
    resp = await client.post(
        "/v1/workspaces",
        json={"name": "test-ws", "ttl_seconds": 3600, "quota_mb": 50},
    )
    assert resp.status_code == 201
    ws = resp.json()
    ws_id = ws["workspace_id"]
    assert ws["name"] == "test-ws"

    # List
    resp = await client.get("/v1/workspaces")
    assert resp.status_code == 200
    assert len(resp.json()["workspaces"]) >= 1

    # Get
    resp = await client.get(f"/v1/workspaces/{ws_id}")
    assert resp.status_code == 200

    # Update
    resp = await client.put(
        f"/v1/workspaces/{ws_id}",
        json={"ttl_seconds": 7200},
    )
    assert resp.status_code == 200
    assert resp.json()["ttl_seconds"] == 7200

    # Snapshot
    resp = await client.post(f"/v1/workspaces/{ws_id}/snapshot")
    assert resp.status_code == 200

    # Restore
    resp = await client.post(f"/v1/workspaces/{ws_id}/restore")
    assert resp.status_code == 200

    # Delete
    resp = await client.delete(f"/v1/workspaces/{ws_id}")
    assert resp.status_code == 200