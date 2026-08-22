"""Tests for JWT, Refresh Token Engine, Scoped API Keys, and RBAC Tenant Isolation."""

import pytest
from datetime import datetime, timezone, timedelta
from thinkdome.security.auth.jwt_engine import (
    create_access_token,
    decode_access_token,
    revoke_jti,
    generate_refresh_token,
    hash_refresh_token,
)
from thinkdome.security.auth.single_sandbox_token import (
    mint_sandbox_access_token,
    verify_sandbox_access_token,
)
from thinkdome.security.identity.core import UserIdentity, RolePolicyEngine


def test_jwt_access_token_minting_and_decoding():
    payload = {"sub": "testuser", "role": "AGENT_STANDARD", "tenant_id": "tenant-a"}
    token = create_access_token(payload, expires_delta=timedelta(minutes=5))
    
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["sub"] == "testuser"
    assert decoded["role"] == "AGENT_STANDARD"
    assert decoded["tenant_id"] == "tenant-a"
    assert "jti" in decoded


def test_jwt_access_token_revocation():
    payload = {"sub": "revokable_user", "role": "FREE"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded is not None
    
    jti = decoded["jti"]
    revoke_jti(jti)
    
    revoked_decoded = decode_access_token(token)
    assert revoked_decoded is None


def test_single_sandbox_access_token():
    sbx_token = mint_sandbox_access_token("sb_12345", username="agent_smith", role="AGENT_STANDARD")
    assert sbx_token is not None
    
    # Valid verification
    payload = verify_sandbox_access_token(sbx_token, target_sandbox_id="sb_12345")
    assert payload is not None
    assert payload["sandbox_id"] == "sb_12345"
    assert payload["sub"] == "agent_smith"
    
    # Mismatched sandbox ID verification should fail
    mismatched = verify_sandbox_access_token(sbx_token, target_sandbox_id="sb_other")
    assert mismatched is None


def test_refresh_token_hashing():
    raw_ref = generate_refresh_token()
    assert raw_ref.startswith("td_ref_")
    
    hashed1 = hash_refresh_token(raw_ref)
    hashed2 = hash_refresh_token(raw_ref)
    assert hashed1 == hashed2
    assert len(hashed1) == 64  # SHA-256 hex string length


def test_rbac_tenant_isolation():
    tenant_a_user = UserIdentity.from_dict({
        "username": "alice",
        "role": "AGENT_STANDARD",
        "tenant_id": "tenant-a"
    })
    
    tenant_b_user = UserIdentity.from_dict({
        "username": "bob",
        "role": "AGENT_STANDARD",
        "tenant_id": "tenant-b"
    })

    sandbox_a = {
        "sandbox_id": "sb_tenant_a",
        "owner": "alice",
        "tenant_id": "tenant-a"
    }

    # Alice can access her sandbox in tenant A
    assert RolePolicyEngine.is_sandbox_accessible(sandbox_a, tenant_a_user) is True

    # Bob (tenant B) CANNOT access Alice's sandbox (tenant A) even with a valid token
    assert RolePolicyEngine.is_sandbox_accessible(sandbox_a, tenant_b_user) is False


def test_rbac_admin_override():
    admin_user = UserIdentity.from_dict({
        "username": "admin",
        "role": "SUPER_ADMIN",
        "tenant_id": "default"
    })
    
    sandbox_a = {
        "sandbox_id": "sb_tenant_a",
        "owner": "alice",
        "tenant_id": "tenant-a"
    }

    # Admin bypasses instance check
    assert RolePolicyEngine.is_sandbox_accessible(sandbox_a, admin_user) is True
