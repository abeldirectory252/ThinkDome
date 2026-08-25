"""Contract tests for the canonical, non-administrative sandbox API namespace."""

import pytest


@pytest.mark.asyncio
async def test_canonical_sandbox_routes_require_authentication(unauthenticated_client):
    """Sandbox resources use /v1/sandboxes while retaining normal auth checks."""
    for path in ("/v1/sandboxes", "/v1/sandboxes/capacity"):
        response = await unauthenticated_client.get(path)
        assert response.status_code == 401


def test_canonical_sandbox_routes_are_registered(app):
    paths = {route.path for route in app.routes}
    assert "/v1/sandboxes" in paths
    assert "/v1/sandboxes/capacity" in paths
    assert "/v1/sandboxes/{sandbox_id}/toggle" in paths
    assert "/v1/sandboxes/{sandbox_id}" in paths
