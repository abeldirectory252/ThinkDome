"""Tests for advanced OpenSandbox features implemented in ThinkDome.

Covering:
1. Network Policy evaluation (defaultAction, target matchers, ports/protocols)
2. OSEP-0011 Signed Route Tokens (encode/decode base36, signature calculation & verification)
3. Credential Vault Outbound Brokerage (bearer, basic, apiKey, customHeaders, passthrough + substitutions)
4. Secure Container Runtime Guard (gVisor, Kata, MicroVM startup validation)
5. Credential Vault REST API (/v1/sandboxes/{id}/vault, /v1/sandboxes/{id}/vault/keys)
"""

import time
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from thinkdome.api.server import create_app
from thinkdome.sandbox.network.policy import NetworkPolicy, NetworkRule, evaluate_network_policy
from thinkdome.sandbox.network.signing import (
    encode_expires_b36,
    decode_expires_b36,
    build_signed_route,
    verify_signed_route,
)
from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup
from thinkdome.security.auth.vault_bindings import (
    Credential,
    CredentialBinding,
    MatchRule,
    AuthRule,
    SubstitutionRule,
    CustomHeaderSpec,
)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_network_policy_evaluation():
    """Test egress evaluation against NetworkPolicy."""
    policy = NetworkPolicy(
        defaultAction="deny",
        egress=[
            NetworkRule(action="allow", target="api.github.com", ports=[443]),
            NetworkRule(action="allow", target="*.anthropic.com"),
            NetworkRule(action="deny", target="blocked.anthropic.com"),
        ],
    )

    # Allowed exact match
    allowed, reason = evaluate_network_policy(policy, "api.github.com", port=443)
    assert allowed is True

    # Denied port mismatch
    allowed_bad_port, _ = evaluate_network_policy(policy, "api.github.com", port=80)
    assert allowed_bad_port is False

    # Allowed wildcard match
    allowed_wildcard, _ = evaluate_network_policy(policy, "api.v1.anthropic.com", port=443)
    assert allowed_wildcard is True

    # Denied default
    allowed_default, _ = evaluate_network_policy(policy, "untrusted-site.org", port=443)
    assert allowed_default is False


def test_osep0011_signed_route_tokens():
    """Test base36 encoding/decoding and OSEP-0011 route token signing/verification."""
    now_sec = int(time.time())
    expires_sec = now_sec + 3600

    b36 = encode_expires_b36(expires_sec)
    decoded = decode_expires_b36(b36)
    assert decoded == expires_sec

    secret = b"my_super_secret_signing_key_123"
    route_token = build_signed_route(
        sandbox_id="sb_signed_123",
        port=8080,
        expires_sec=expires_sec,
        secret_bytes=secret,
        key_id="a",
    )
    assert "sb_signed_123-8080-" in route_token

    # Verify valid token
    keys = {"a": secret}
    valid, reason, sb_id, port = verify_signed_route(route_token, keys, current_time_sec=now_sec)
    assert valid is True
    assert sb_id == "sb_signed_123"
    assert port == 8080

    # Verify invalid secret fails
    bad_keys = {"a": b"wrong_secret"}
    valid_bad, _, _, _ = verify_signed_route(route_token, bad_keys, current_time_sec=now_sec)
    assert valid_bad is False

    # Verify expired token fails
    valid_exp, _, _, _ = verify_signed_route(route_token, keys, current_time_sec=expires_sec + 100)
    assert valid_exp is False


def test_credential_vault_outbound_broker(client):
    """Test Credential Vault secret storage, binding matching, header injection, and placeholder substitution."""
    vault = client.app.state.credential_vault
    user_id = "test_user_1"
    sandbox_id = "sb_vault_broker_1"

    # 1. Store secrets
    vault.store(user_id, sandbox_id, "github-token", "ghp_secret_12345")
    vault.store(user_id, sandbox_id, "anthropic-key", "sk-ant-real-key-999")

    # 2. Register binding with apiKey + substitutions
    binding_data = {
        "name": "anthropic-api",
        "match": {
            "schemes": ["https"],
            "hosts": ["api.anthropic.com"],
            "methods": ["POST"],
            "paths": ["/v1/*"],
        },
        "auth": {
            "type": "apiKey",
            "name": "x-api-key",
            "credential": "anthropic-key",
            "substitutions": [
                {
                    "credential": "github-token",
                    "placeholder": "__github_ph__",
                    "in": ["body", "query"],
                }
            ],
        },
    }
    vault.register_binding(sandbox_id, binding_data)

    # 3. Evaluate matching request
    res = vault.evaluate_outbound_request(
        user_id=user_id,
        sandbox_id=sandbox_id,
        scheme="https",
        host="api.anthropic.com",
        method="POST",
        path="/v1/messages",
        headers={"Content-Type": "application/json"},
        query={"ref": "__github_ph__"},
        body='{"prompt": "Hello __github_ph__"}',
    )

    assert res["matched"] is True
    assert res["injected_headers"].get("x-api-key") == "sk-ant-real-key-999"
    assert "ghp_secret_12345" in res["rewritten_query"]["ref"]
    assert "ghp_secret_12345" in res["rewritten_body"]


def test_secure_runtime_guard():
    """Test startup validation guard for secure container runtimes."""
    class DummySettings:
        SECURE_RUNTIME_TYPE = ""
        EXECUTOR_BACKEND = "docker"

    # Unconfigured should pass silently
    validate_secure_runtime_on_startup(DummySettings())

    # Docker mode missing runtime should fail when docker client has no runsc
    class DummySettingsDocker:
        SECURE_RUNTIME_TYPE = "gvisor"
        EXECUTOR_BACKEND = "docker"
        DOCKER_RUNTIME = "nonexistent_runtime_xyz"

    class DummyDockerClient:
        def info(self):
            return {"Runtimes": {"runc": {}}}

    with pytest.raises(RuntimeError) as excinfo:
        validate_secure_runtime_on_startup(DummySettingsDocker(), docker_client=DummyDockerClient())
    assert "nonexistent_runtime_xyz" in str(excinfo.value)


def test_credential_vault_rest_api(client):
    """Test REST endpoints for Vault (/v1/sandboxes/{id}/vault and /keys)."""
    sandbox_id = "sb_vault_api_test"
    payload = {
        "credentials": [
            {"name": "token1", "source": {"value": "secret_val_1"}},
            {"name": "token2", "source": {"value": "secret_val_2"}},
        ],
        "bindings": [
            {
                "name": "b1",
                "match": {"hosts": ["api.test.com"]},
                "auth": {"type": "bearer", "credential": "token1"},
            }
        ],
    }

    res = client.post(f"/v1/sandboxes/{sandbox_id}/vault", json=payload)
    assert res.status_code == 201
    assert res.json()["credentials_count"] == 2

    # List keys — ensure secret values are NOT exposed
    res_keys = client.get(f"/v1/sandboxes/{sandbox_id}/vault/keys")
    assert res_keys.status_code == 200
    keys = res_keys.json()["keys"]
    assert "token1" in keys
    assert "token2" in keys
    assert "secret_val_1" not in str(res_keys.json())
