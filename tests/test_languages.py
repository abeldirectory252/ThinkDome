"""Language and runtime endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_list_languages(client):
    resp = await client.get("/v1/languages")
    assert resp.status_code == 200
    langs = resp.json()
    names = [l["name"] for l in langs]
    assert "python" in names


@pytest.mark.asyncio
async def test_python_packages(client):
    resp = await client.get("/v1/languages/python/packages")
    assert resp.status_code == 200
    pkgs = resp.json()
    names = [p["name"] for p in pkgs]
    assert "numpy" in names
    assert "pandas" in names


@pytest.mark.asyncio
async def test_runtimes(client):
    resp = await client.get("/v1/runtimes")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1