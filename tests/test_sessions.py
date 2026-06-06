"""Session endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_session_lifecycle(client):
    # Create session
    resp = await client.post(
        "/v1/sessions",
        json={"language": "python", "timeout_ms": 30000},
    )
    assert resp.status_code == 201
    session = resp.json()
    sid = session["session_id"]
    assert session["status"] == "active"

    # Execute in session
    resp = await client.post(
        f"/v1/sessions/{sid}/exec",
        json={"code": "x = 10", "timeout_ms": 5000},
    )
    assert resp.status_code == 200

    # Execute again (should have context)
    resp = await client.post(
        f"/v1/sessions/{sid}/exec",
        json={"code": "print(x)", "timeout_ms": 5000},
    )
    assert resp.status_code == 200
    assert "10" in resp.json()["stdout"]

    # Get session info
    resp = await client.get(f"/v1/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["execution_count"] == 2

    # Close session
    resp = await client.delete(f"/v1/sessions/{sid}")
    assert resp.status_code == 200