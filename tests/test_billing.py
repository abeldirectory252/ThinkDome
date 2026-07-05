"""Tests for billing API endpoints, invoice compilation, and PDF downloads."""

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
async def test_billing_unauthorized(client):
    # Retrieve billing reports without authorization
    resp = await client.get("/v1/admin/billing")
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_billing_cycles_and_breakdown(client, api_keys, app):
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}

    # Add a mock sandbox
    db = app.state.db_service
    sandbox_id = "sb_billing_test_123"
    db.create_sandbox(
        sandbox_id=sandbox_id,
        name="Billing Test Env",
        owner="api_key_client",
        memory_mb=512,
        cpu_cores=2.0,
        timeout_sec=60,
        network_enabled=True,
        cost_per_hour=0.085
    )

    # 1. Fetch current cycle reports
    resp = await client.get("/v1/admin/billing?cycle=this", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "label" in data
    assert "total" in data
    assert "budgetPct" in data
    assert "sandboxes" in data
    assert sandbox_id in data["sandboxes"]
    assert data["sandboxes"][sandbox_id]["rate"] == "$0.085/hr"

    # 2. Fetch last cycle reports
    resp = await client.get("/v1/admin/billing?cycle=last", headers=headers)
    assert resp.status_code == 200
    data_last = resp.json()
    assert "label" in data_last
    assert data_last["label"] != data["label"]

@pytest.mark.asyncio
async def test_invoice_compilation_and_download(client, api_keys, app):
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}

    # Compile invoice
    resp = await client.post("/v1/admin/billing/invoice?cycle=this", headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert "invoice_id" in res_data
    assert "download_url" in res_data
    invoice_id = res_data["invoice_id"]
    download_url = res_data["download_url"]

    # Download with bearer token
    resp_download = await client.get(download_url, headers=headers)
    assert resp_download.status_code == 200
    assert resp_download.headers["content-type"] == "application/pdf"
    assert b"%PDF-1.4" in resp_download.content

    # Download using token as query parameter
    query_download_url = f"{download_url}?token={api_keys['ADMIN']}"
    resp_query = await client.get(query_download_url)
    assert resp_query.status_code == 200
    assert resp_query.headers["content-type"] == "application/pdf"
    assert b"%PDF-1.4" in resp_query.content

    # Download non-existent invoice ID
    resp_404 = await client.get("/v1/admin/billing/invoice/download/inv_fake123", headers=headers)
    assert resp_404.status_code == 404
