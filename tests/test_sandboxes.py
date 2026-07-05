"""Tests for sandbox database persistence, billing costs, and status toggles."""

import pytest


@pytest.fixture
def api_keys(app):
    """Fixture to generate test API keys for LLM and ADMIN roles."""
    auth_svc = app.state.auth_service
    llm_key = auth_svc.create_api_key("LLM Test Key", token_type="LLM")
    admin_key = auth_svc.create_api_key("Admin Test Key", token_type="ADMIN")
    return {
        "LLM": llm_key["token"],
        "ADMIN": admin_key["token"]
    }


@pytest.mark.asyncio
async def test_sandbox_unauthorized(client):
    # Fetch without auth
    resp = await client.get("/v1/admin/sandboxes")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sandbox_lifecycle(client, api_keys):
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}

    # 1. List sandboxes
    resp = await client.get("/v1/admin/sandboxes", headers=headers)
    assert resp.status_code == 200
    initial_count = len(resp.json())

    # 2. Create sandbox (RAM=512MB, CPU=2, Timeout=60s, Network=True)
    payload = {
        "name": "Data Analytics Env",
        "memory_mb": 512,
        "cpu_cores": 2.0,
        "timeout_sec": 60,
        "network_enabled": True
    }
    resp = await client.post("/v1/admin/sandboxes", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Data Analytics Env"
    assert data["memory_mb"] == 512
    assert data["cpu_cores"] == 2.0
    assert data["timeout_sec"] == 60
    assert data["network_enabled"] is True
    # Cost should be: (512/128)*0.01 + 2*0.02 + 0.005 = 0.04 + 0.04 + 0.005 = 0.085
    assert abs(data["cost_per_hour"] - 0.085) < 0.001
    assert data["status"] == "active"
    sandbox_id = data["sandbox_id"]

    # 3. List sandboxes again
    resp = await client.get("/v1/admin/sandboxes", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == initial_count + 1
    assert any(s["sandbox_id"] == sandbox_id for s in resp.json())

    # 4. Toggle sandbox status (active -> stopped)
    resp = await client.post(f"/v1/admin/sandboxes/{sandbox_id}/toggle", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "stopped"

    # Verify toggle in list
    resp = await client.get("/v1/admin/sandboxes", headers=headers)
    target = next(s for s in resp.json() if s["sandbox_id"] == sandbox_id)
    assert target["status"] == "stopped"

    # 5. Delete sandbox
    resp = await client.delete(f"/v1/admin/sandboxes/{sandbox_id}", headers=headers)
    assert resp.status_code == 200
    assert "terminated" in resp.json()["message"]

    # Verify deleted
    resp = await client.get("/v1/admin/sandboxes", headers=headers)
    assert len(resp.json()) == initial_count


@pytest.mark.asyncio
async def test_orchestrate_no_sandbox_fails(client, api_keys, app):
    # Clear all active sandboxes
    app.state.db_service.execute("DELETE FROM sandboxes")

    payload = {
        "type": "tool_use",
        "id": "toolu_no_sandbox",
        "name": "run_code",
        "input": {
            "code": "print('Test')",
            "language": "python"
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "No active sandbox environment found" in resp.json()["error"]["message"]
