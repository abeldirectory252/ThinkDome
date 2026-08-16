"""Tests for Unified Ingress Gateway (Wildcard, Header, URI routing strategies)."""

import time
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from thinkdome.sandbox.network.ingress import (
    IngressGateway,
    RoutingStrategy,
    THINKDOME_INGRESS_HEADER,
)
from thinkdome.sandbox.network.signing import build_signed_route


@pytest.fixture
def secret_keys():
    return {"a": b"secret_gateway_key_999"}


def test_ingress_header_strategy(secret_keys):
    """Test routing via ThinkDome-Ingress-To header."""
    gateway = IngressGateway(secret_keys=secret_keys)

    app = FastAPI()

    @app.get("/{full_path:path}")
    def handle_request(request: Request, full_path: str):
        route = gateway.resolve_route(request)
        return {
            "sandbox_id": route.sandbox_id,
            "port": route.port,
            "strategy": route.strategy_used.value,
        }

    client = TestClient(app)

    # 1. Unsigned header 'sb_head_1:8080'
    res = client.get("/api/test", headers={THINKDOME_INGRESS_HEADER: "sb_head_1:8080"})
    assert res.status_code == 200
    data = res.json()
    assert data["sandbox_id"] == "sb_head_1"
    assert data["port"] == 8080
    assert data["strategy"] == "header"

    # 2. Signed header token
    now_sec = int(time.time())
    token = build_signed_route(
        sandbox_id="sb_head_signed",
        port=9000,
        expires_sec=now_sec + 3600,
        secret_bytes=secret_keys["a"],
        key_id="a",
    )
    res_signed = client.get("/api/test", headers={THINKDOME_INGRESS_HEADER: token})
    assert res_signed.status_code == 200
    data_signed = res_signed.json()
    assert data_signed["sandbox_id"] == "sb_head_signed"
    assert data_signed["port"] == 9000
    assert data_signed["strategy"] == "header"


def test_ingress_uri_strategy(secret_keys):
    """Test routing via URI path (/sandboxes/{id}/proxy/{port}/...)."""
    gateway = IngressGateway(secret_keys=secret_keys)

    app = FastAPI()

    @app.get("/{full_path:path}")
    def handle_request(request: Request, full_path: str):
        route = gateway.resolve_route(request)
        return {
            "sandbox_id": route.sandbox_id,
            "port": route.port,
            "strategy": route.strategy_used.value,
            "target_path": route.target_path,
        }

    client = TestClient(app)

    # Path routing: /sandboxes/sb_uri_1/proxy/3000/v1/health
    res = client.get("/sandboxes/sb_uri_1/proxy/3000/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["sandbox_id"] == "sb_uri_1"
    assert data["port"] == 3000
    assert data["strategy"] == "uri"
    assert data["target_path"] == "/v1/health"


def test_ingress_wildcard_strategy(secret_keys):
    """Test routing via Host header (<sandbox_id>-<port>.<domain>)."""
    gateway = IngressGateway(secret_keys=secret_keys)

    app = FastAPI()

    @app.get("/{full_path:path}")
    def handle_request(request: Request, full_path: str):
        route = gateway.resolve_route(request)
        return {
            "sandbox_id": route.sandbox_id,
            "port": route.port,
            "strategy": route.strategy_used.value,
        }

    client = TestClient(app)

    # Host header: sb_wild_1-5000.sandboxes.local
    res = client.get("/index.html", headers={"Host": "sb_wild_1-5000.sandboxes.local"})
    assert res.status_code == 200
    data = res.json()
    assert data["sandbox_id"] == "sb_wild_1"
    assert data["port"] == 5000
    assert data["strategy"] == "wildcard"
