"""Automated Tests for ThinkDome Frappe-Style Framework & /api/method RPC Engine."""

from __future__ import annotations

import os
import pytest
from httpx import AsyncClient, ASGITransport

import thinkdome


@pytest.mark.asyncio
async def test_rpc_method_endpoint_and_permissions(app):
    transport = ASGITransport(app=app)
    admin_token = app.state.auth_service.create_api_key("Admin User", token_type="ADMIN")["token"]
    user_token = app.state.auth_service.create_api_key("Standard User", token_type="AGENT_STANDARD")["token"]

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Navigation RPC call (Allowed for guest/user)
        resp = await client.post("/api/method/thinkdome.core.ui.api.get_navigation", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "workspaces" in data["message"]

        # 2. Test Admin-only method with standard user -> Expect 403 PermissionError
        resp_forbidden = await client.post(
            "/api/method/thinkdome.core.ui.api.setup_dynamic_ui",
            json={"config": {"workspaces": []}},
            headers=user_headers,
        )
        assert resp_forbidden.status_code == 403
        assert resp_forbidden.json()["exc_type"] == "PermissionError"

        # 3. Test Admin-only method with admin user -> Expect 200 Success
        resp_admin = await client.post(
            "/api/method/thinkdome.core.ui.api.setup_dynamic_ui",
            json={"config": {"workspaces": [], "pages": []}},
            headers=admin_headers,
        )
        assert resp_admin.status_code == 200
        assert "message" in resp_admin.json()

        # 4. Test non-existent method -> Expect 404 AttributeError
        resp_404 = await client.post("/api/method/nonexistent.module.method", headers=admin_headers)
        assert resp_404.status_code == 404
        assert resp_404.json()["exc_type"] == "AttributeError"
