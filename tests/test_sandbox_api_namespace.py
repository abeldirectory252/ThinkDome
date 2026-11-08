"""Contract tests for the canonical, non-administrative sandbox API namespace."""

import pytest

from thinkdome.security.api.admin import _serialize_sandbox


@pytest.mark.asyncio
async def test_canonical_sandbox_routes_require_authentication(unauthenticated_client):
    """Sandbox resources use /v1/sandboxes while retaining normal auth checks."""
    for path in ("/v1/sandboxes", "/v1/sandboxes/capacity"):
        response = await unauthenticated_client.get(path)
        assert response.status_code == 401


def _collect_app_paths(app) -> set[str]:
    paths = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        elif hasattr(route, "original_router") and hasattr(route, "include_context"):
            prefix = getattr(route.include_context, "prefix", "")
            for inner in route.original_router.routes:
                if hasattr(inner, "path"):
                    paths.add(f"{prefix}{inner.path}")
        elif hasattr(route, "routes"):
            for sub_route in route.routes:
                if hasattr(sub_route, "path"):
                    paths.add(sub_route.path)
    return paths


def test_canonical_sandbox_routes_are_registered(app):
    paths = _collect_app_paths(app)
    assert "/v1/sandboxes" in paths
    assert "/v1/sandboxes/capacity" in paths
    assert "/v1/sandboxes/{sandbox_id}/toggle" in paths
    assert "/v1/sandboxes/{sandbox_id}" in paths


def test_dashboard_index_alias_is_registered(app):
    paths = _collect_app_paths(app)
    assert "/index.html" in paths


def test_sandbox_serializer_exposes_stable_resource_schema():
    payload = _serialize_sandbox(
        {"id": "sb_test", "memory_limit": 512, "cpu_limit": 2.0, "status": "Running"}
    )
    assert payload["sandbox_id"] == "sb_test"
    assert payload["memory_mb"] == 512
    assert payload["cpu_cores"] == 2.0
    assert payload["status"] == "active"
