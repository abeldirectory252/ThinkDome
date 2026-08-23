"""Regression tests for public API server entrypoints."""

from fastapi import FastAPI
from fastapi.responses import Response
from starlette.requests import Request


def test_legacy_asgi_module_exposes_an_application():
    from thinkdome.server import app, create_app, start_server

    assert isinstance(app, FastAPI)
    assert callable(create_app)
    assert callable(start_server)


def test_main_uses_the_public_api_factory(monkeypatch):
    import thinkdome.main as main_module

    captured = {}

    def fake_run(target, **kwargs):
        captured["target"] = target
        captured.update(kwargs)

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    main_module.main()

    assert captured["target"] == "thinkdome.api.server:create_app"
    assert captured["factory"] is True


async def test_refresh_accepts_the_http_only_cookie():
    from thinkdome.security.api.auth import RefreshRequest, refresh

    class AuthServiceStub:
        def rotate_refresh_token(self, token, actor_ip):
            assert token == "refresh-from-cookie"
            assert actor_ip == "127.0.0.1"
            return {"access_token": "new-access", "refresh_token": "new-refresh"}

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/auth/refresh",
        "headers": [(b"cookie", b"refresh_token=refresh-from-cookie")],
        "client": ("127.0.0.1", 8000),
    })
    response = Response()

    tokens = await refresh(request, response, RefreshRequest(), AuthServiceStub())

    assert tokens["access_token"] == "new-access"
    assert len(response.headers.getlist("set-cookie")) == 2


def test_control_plane_nodes_degrades_when_registry_is_unavailable():
    import asyncio
    from thinkdome.api.routes.control_plane import list_ready_nodes

    class BrokenRepository:
        def get_ready_heartbeats(self):
            raise RuntimeError("database is not ready")

    class Lifecycle:
        repository = BrokenRepository()

    assert asyncio.run(list_ready_nodes({}, Lifecycle())) == {"nodes": []}


def test_auth_me_does_not_forge_an_admin_identity():
    import asyncio
    from thinkdome.security.api.auth import get_me

    result = asyncio.run(get_me({"username": "alice", "role": "AGENT_STANDARD"}))
    assert result["user"]["username"] == "alice"
    assert result["user"]["role"] == "AGENT_STANDARD"
