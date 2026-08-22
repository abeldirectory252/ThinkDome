"""Tests for Administrator controls (network policy, runtime availability, emergency kill switch, container security)."""

import pytest
from fastapi.testclient import TestClient
from thinkdome.api.server import create_app
from thinkdome.sandbox.security.runtime_guard import get_secure_docker_config_kwargs


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_docker_security_hardening_kwargs():
    kwargs = get_secure_docker_config_kwargs()
    assert kwargs["privileged"] is False
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["read_only"] is True
    assert "/tmp" in kwargs["tmpfs"]
    assert kwargs["pids_limit"] == 100
    assert kwargs["mem_limit"] == "512m"


def test_admin_network_policy_endpoints(client):
    # Admin login or auth header
    login_resp = client.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch policy
    get_res = client.get("/v1/admin/network-policy", headers=headers)
    assert get_res.status_code == 200
    assert "allowlist" in get_res.json()

    # Update policy
    put_res = client.put(
        "/v1/admin/network-policy",
        json={
            "tenant_id": "default",
            "allowlist": [r".*\.api\.openai\.com$"],
            "denylist": [r"^169\.254\.169\.254$"]
        },
        headers=headers
    )
    assert put_res.status_code == 200
    assert put_res.json()["status"] == "success"


def test_admin_runtime_toggles_and_kill_switch(client):
    login_resp = client.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # List runtimes
    runtimes_res = client.get("/v1/admin/runtimes", headers=headers)
    assert runtimes_res.status_code == 200
    assert "python" in runtimes_res.json()["runtimes"]

    # Toggle runtime
    toggle_res = client.post(
        "/v1/admin/runtimes/toggle",
        json={"runtime": "go", "enabled": True},
        headers=headers
    )
    assert toggle_res.status_code == 200
    assert toggle_res.json()["enabled"] is True

    # Kill switch
    kill_res = client.post(
        "/v1/admin/kill-switch",
        json={"freeze_creation": True, "purge_sandboxes": False},
        headers=headers
    )
    assert kill_res.status_code == 200
    assert kill_res.json()["frozen"] is True
