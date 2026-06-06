"""Execution endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_simple_execute(client):
    resp = await client.post(
        "/v1/execute",
        json={
            "code": "print('hello world')",
            "timeout_ms": 5000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "hello world" in data["stdout"]
    assert data["exit_code"] == 0
    assert data["timed_out"] is False


@pytest.mark.asyncio
async def test_interactive_mode(client):
    resp = await client.post(
        "/v1/execute",
        json={
            "code": "x = 42\nx",
            "last_line_interactive": True,
            "timeout_ms": 5000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "42" in data["stdout"]


@pytest.mark.asyncio
async def test_syntax_error(client):
    resp = await client.post(
        "/v1/execute",
        json={
            "code": "def foo(\n",
            "timeout_ms": 5000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exit_code"] != 0
    assert data["stderr"] != ""


@pytest.mark.asyncio
async def test_timeout(client):
    resp = await client.post(
        "/v1/execute",
        json={
            "code": "import time; time.sleep(30)",
            "timeout_ms": 500,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timed_out"] is True


@pytest.mark.asyncio
async def test_batch_execute(client):
    resp = await client.post(
        "/v1/execute/batch",
        json={
            "executions": [
                {"code": "print('step1')", "timeout_ms": 5000},
                {"code": "print('step2')", "timeout_ms": 5000},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 2
    assert "step1" in data["results"][0]["stdout"]
    assert "step2" in data["results"][1]["stdout"]


@pytest.mark.asyncio
async def test_file_injection(client):
    import base64

    content = base64.b64encode(b"name,value\nalice,1\nbob,2").decode()
    resp = await client.post(
        "/v1/execute",
        json={
            "code": "with open('data.csv') as f: print(f.read())",
            "timeout_ms": 5000,
            "files": [{"path": "data.csv", "content_base64": content}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "alice" in data["stdout"]