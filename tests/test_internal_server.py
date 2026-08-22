import httpx
import pytest
from fastapi import FastAPI

from thinkdome.control_plane.internal_server import create_internal_control_plane_app


class FakeRegistry:
    def heartbeat(self, payload):
        return None

    def reconcile_expired(self):
        return 0


@pytest.mark.asyncio
async def test_internal_control_plane_contains_only_private_routes():
    app = create_internal_control_plane_app(FakeRegistry(), reconcile_interval_seconds=0.01)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal")
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["component"] == "control-plane-internal"
    paths = [getattr(route, "path", "") for route in app.routes]
    assert all(path.startswith("/internal/") or path == "/healthz" for path in paths if path)
    await client.aclose()
