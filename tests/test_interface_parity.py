"""Tests for multi-interface consistency across Web UI, REST/curl API, and Python SDK."""

import pytest
from fastapi.testclient import TestClient
from thinkdome.api.server import create_app
from thinkdome.sandbox.sdk import Sandbox, SandboxResult


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_api_keys_crud_endpoints(client):
    login_resp = client.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create scoped API key
    create_res = client.post(
        "/v1/api-keys/",
        json={"display_name": "Test SDK Key", "token_type": "SDK", "rate_limit_tier": "standard"},
        headers=headers
    )
    assert create_res.status_code == 201
    key_info = create_res.json()
    assert "token" in key_info
    assert key_info["token"].startswith("td_sdk_")
    key_id = key_info["key_id"]
    api_key_token = key_info["token"]

    # List keys
    list_res = client.get("/v1/api-keys/", headers=headers)
    assert list_res.status_code == 200
    assert any(k["key_id"] == key_id for k in list_res.json())

    # Revoke key by ID
    revoke_res = client.delete(f"/v1/api-keys/{key_id}", headers=headers)
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "success"


def test_python_sdk_api_key_and_purpose_params():
    sdk_sandbox = Sandbox(
        api_key="td_sdk_testkey12345",
        purpose="data_analysis",
        ttl=300,
        language="python"
    )
    
    assert sdk_sandbox.api_key == "td_sdk_testkey12345"
    assert sdk_sandbox.purpose == "data_analysis"
    assert sdk_sandbox.ttl == 300
    assert sdk_sandbox.metadata.get("purpose") == "data_analysis"
    
    # Test single-sandbox token minting
    sbx_token = sdk_sandbox.get_sandbox_token()
    assert sbx_token is not None
