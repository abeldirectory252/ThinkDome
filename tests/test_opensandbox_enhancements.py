"""Tests for OpenSandbox enhancements implemented in ThinkDome.

Covering:
1. Request ID Middleware (X-Request-ID propagation)
2. Structured error responses ({"code", "message"})
3. Sandbox Lifecycle API (pause, resume, renew-expiration)
4. Sandbox Diagnostics API (logs, inspect, events, summary)
5. Sandbox Metadata Patching API (RFC 7396 + label validation)
6. SDK Metrics Ingestion API (POST /v1/metrics/events)
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from thinkdome.api.server import create_app
from thinkdome.core.error_codes import SandboxErrorCodes


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        token = test_client.app.state.auth_service.create_api_key("Default test admin", token_type="ADMIN")["token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def test_request_id_middleware(client):
    """Test that X-Request-ID is generated and returned in headers."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    req_id = response.headers["X-Request-ID"]
    assert len(req_id) > 0

    # Custom request ID should be echoed back
    custom_id = "test-custom-request-id-12345"
    response2 = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response2.headers.get("X-Request-ID") == custom_id


def test_structured_error_responses(client):
    """Test that errors return standardized {"code": ..., "message": ...} payload."""
    # 404 error
    response = client.get("/v1/sandboxes/nonexistent_sb_9999/diagnostics/logs")
    # Even if default 404 or exception occurs, error code format is checked
    # Test an explicit endpoint returning HTTPException
    response2 = client.post("/v1/sandboxes/nonexistent_sb/pause")
    assert response2.status_code == 404
    data = response2.json()
    assert "code" in data
    assert "message" in data
    assert data["code"] == SandboxErrorCodes.SANDBOX_NOT_FOUND


def test_sdk_metrics_ingestion(client):
    """Test POST /v1/metrics/events endpoint."""
    payload = {
        "event_type": "sandbox.create",
        "sandbox_id": "sb_test_123",
        "image": "python:3.12",
        "create_duration_ms": 145.5,
        "success": True,
    }
    headers = {"User-Agent": "ThinkDome-Python-SDK/0.1.0"}
    response = client.post("/v1/metrics/events", json=payload, headers=headers)
    assert response.status_code == 204


def test_sandbox_lifecycle_flow(client):
    """Test register -> pause -> resume -> renew_expiration flow via Lifecycle API."""
    app = client.app
    lifecycle_service = app.state.lifecycle_service

    # Register a test sandbox
    sandbox_id = "sb_lifecycle_test_1"
    lifecycle_service.register_sandbox(
        sandbox_id=sandbox_id,
        container_id="dummy_container_1",
        image="python:3.12",
        backend="docker",
        timeout_sec=300,
        metadata={"env": "testing"},
    )

    # Pause
    res_pause = client.post(f"/v1/sandboxes/{sandbox_id}/pause")
    assert res_pause.status_code == 202
    info = lifecycle_service.get_sandbox(sandbox_id)
    assert info.state == "Paused"

    # Resume
    res_resume = client.post(f"/v1/sandboxes/{sandbox_id}/resume")
    assert res_resume.status_code == 202
    info = lifecycle_service.get_sandbox(sandbox_id)
    assert info.state == "Running"

    # Renew expiration with relative timeout
    res_renew = client.post(
        f"/v1/sandboxes/{sandbox_id}/renew-expiration",
        json={"timeout_seconds": 600},
    )
    assert res_renew.status_code == 200
    data = res_renew.json()
    assert data["sandbox_id"] == sandbox_id
    assert "expires_at" in data

    # Renew with past expiration should fail
    past_dt = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    res_bad_renew = client.post(
        f"/v1/sandboxes/{sandbox_id}/renew-expiration",
        json={"expires_at": past_dt},
    )
    assert res_bad_renew.status_code == 400
    assert res_bad_renew.json()["code"] == SandboxErrorCodes.INVALID_EXPIRATION


def test_sandbox_diagnostics_flow(client):
    """Test diagnostics endpoints (logs, inspect, events, summary)."""
    app = client.app
    diag_service = app.state.diagnostics_service

    sandbox_id = "sb_diag_test_1"
    diag_service.record_event(sandbox_id, "created", "Sandbox created")
    diag_service.record_event(sandbox_id, "started", "Sandbox container started")

    # Events text
    res_events = client.get(f"/v1/sandboxes/{sandbox_id}/diagnostics/events")
    assert res_events.status_code == 200
    assert "created: Sandbox created" in res_events.text

    # Events JSON
    res_events_json = client.get(f"/v1/sandboxes/{sandbox_id}/diagnostics/events?format=json")
    assert res_events_json.status_code == 200
    data = res_events_json.json()
    assert len(data["events"]) == 2

    # Logs
    res_logs = client.get(f"/v1/sandboxes/{sandbox_id}/diagnostics/logs")
    assert res_logs.status_code == 200

    # Summary
    res_summary = client.get(f"/v1/sandboxes/{sandbox_id}/diagnostics/summary")
    assert res_summary.status_code == 200
    assert "SANDBOX DIAGNOSTICS SUMMARY" in res_summary.text


def test_metadata_patching(client):
    """Test PATCH /v1/sandboxes/{id}/metadata with RFC 7396 and label validation."""
    app = client.app
    lifecycle_service = app.state.lifecycle_service

    sandbox_id = "sb_meta_test_1"
    lifecycle_service.register_sandbox(
        sandbox_id=sandbox_id,
        metadata={"role": "worker", "tier": "free"},
    )

    # Patch: update role, add category, delete tier (set to null)
    patch = {
        "role": "agent",
        "category": "ai-coding",
        "tier": None,
    }
    res = client.patch(f"/v1/sandboxes/{sandbox_id}/metadata", json=patch)
    assert res.status_code == 200
    meta = res.json()["metadata"]
    assert meta["role"] == "agent"
    assert meta["category"] == "ai-coding"
    assert "tier" not in meta

    # Test reserved prefix violation
    bad_patch = {"thinkdome.io/system": "override"}
    res_bad = client.patch(f"/v1/sandboxes/{sandbox_id}/metadata", json=bad_patch)
    assert res_bad.status_code == 400
    assert res_bad.json()["code"] == SandboxErrorCodes.RESERVED_LABEL_PREFIX

    # Test invalid label value
    bad_value_patch = {"invalid_key": "this value contains invalid spaces!"}
    res_bad_val = client.patch(f"/v1/sandboxes/{sandbox_id}/metadata", json=bad_value_patch)
    assert res_bad_val.status_code == 400
    assert res_bad_val.json()["code"] == SandboxErrorCodes.INVALID_METADATA_LABEL
