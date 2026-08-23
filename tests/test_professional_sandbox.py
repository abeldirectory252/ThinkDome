"""Integration tests for the professional sandbox token system and privilege matrix."""

import hashlib
import pytest
import json

@pytest.fixture
def auth_service(app):
    return app.state.auth_service

@pytest.fixture
def db_service(app):
    return app.state.db_service

@pytest.mark.asyncio
async def test_professional_token_generation_and_hashing(auth_service, db_service):
    # Test generation for all six token types
    token_types = ["LLM", "WEB", "SDK", "CURL", "ORCH", "IDE"]
    expected_prefixes = {
        "LLM": "td_llm_",
        "WEB": "td_web_",
        "SDK": "td_sdk_",
        "CURL": "td_curl_",
        "ORCH": "td_orch_",
        "IDE": "td_ide_"
    }

    for t_type in token_types:
        key_data = auth_service.create_api_key(f"Test Key {t_type}", token_type=t_type)
        plaintext_token = key_data["token"]
        key_id = key_data["key_id"]
        
        # Verify correct prefix
        prefix = expected_prefixes[t_type]
        assert plaintext_token.startswith(prefix)
        
        # Hash of the token should be stored in the DB
        hashed = hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()
        
        # Query DB directly to verify plaintext token is NOT stored, but the hash is
        row_plaintext = db_service.fetch_one("SELECT 1 FROM api_keys WHERE token = ?", (plaintext_token,))
        assert row_plaintext is None  # Should not find by plaintext
        
        row_hashed = db_service.fetch_one("SELECT * FROM api_keys WHERE token = ?", (hashed,))
        assert row_hashed is not None  # Should find by hash
        assert row_hashed["key_id"] == key_id
        assert row_hashed["token_type"] == t_type
        assert row_hashed["masked_token"] == f"{prefix}••••••••{plaintext_token[-4:]}"

@pytest.mark.asyncio
async def test_verify_token_hashing_and_fallback(auth_service):
    # Create key
    key_data = auth_service.create_api_key("Fallback Test", token_type="SDK")
    plaintext_token = key_data["token"]
    
    # 1. Verify verification works via hash lookup
    identity = auth_service.verify_token(plaintext_token)
    assert identity is not None
    assert identity["role"] == "SDK"
    assert identity["key_id"] == key_data["key_id"]

    # 2. Pre-seed a plaintext key manually to verify compatibility fallback
    import secrets
    compat_key_id = f"key_compat_{secrets.token_hex(4)}"
    compat_token = f"raw_plaintext_unhashed_token_{secrets.token_hex(4)}"
    
    auth_service.db_service.execute(
        """
        INSERT INTO api_keys (token, key_id, display_name, token_type, created_at, expires_at, status, masked_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (compat_token, compat_key_id, "Compat Test", "WEB", "2026-07-05T12:00:00", None, "active", "td_web_••••••••token")
    )
    
    # Verify fallback lookup succeeds
    identity_compat = auth_service.verify_token(compat_token)
    assert identity_compat is not None
    assert identity_compat["role"] == "WEB"
    assert identity_compat["key_id"] == compat_key_id

@pytest.mark.asyncio
async def test_orchestrator_privilege_enforcement_fine_grained(client, auth_service, db_service):
    # Setup test sandboxes
    db_service.create_sandbox(
        sandbox_id="test_sandbox_node",
        name="Test Env",
        owner="api_key_client",
        memory_mb=256,
        cpu_cores=1.0,
        timeout_sec=30,
        network_enabled=False,
        cost_per_hour=0.02
    )

    # 1. Test LLM Token (should only run code, not files)
    llm_key = auth_service.create_api_key("LLM Limit Test", token_type="LLM")["token"]
    headers_llm = {"Authorization": f"Bearer {llm_key}", "X-Sandbox-Id": "test_sandbox_node"}
    
    # run_code: success
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_llm_1", "name": "run_code", "input": {"code": "print('ok')", "language": "python"}
    }, headers=headers_llm)
    assert res.status_code == 200
    assert res.json()["is_error"] is False

    # read_file: denied
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_llm_2", "name": "read_file", "input": {"path": "test.txt"}
    }, headers=headers_llm)
    assert res.status_code == 200
    assert res.json()["is_error"] is True
    assert "not permitted" in res.json()["content"]

    # 2. Test WEB Token (run_code + file CRUD allowed, web_search denied)
    web_key = auth_service.create_api_key("WEB Limit Test", token_type="WEB")["token"]
    headers_web = {"Authorization": f"Bearer {web_key}", "X-Sandbox-Id": "test_sandbox_node"}
    
    # write_file: allowed
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_web_1", "name": "write_file", "input": {"path": "test.txt", "content": "hello"}
    }, headers=headers_web)
    assert res.status_code == 200
    assert res.json()["is_error"] is False

    # web_search: denied
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_web_2", "name": "web_search", "input": {"query": "test"}
    }, headers=headers_web)
    assert res.status_code == 200
    assert res.json()["is_error"] is True
    assert "not permitted" in res.json()["content"]

    # 3. Test SDK Token (web_search allowed, destructive shell denied)
    sdk_key = auth_service.create_api_key("SDK Limit Test", token_type="SDK")["token"]
    headers_sdk = {"Authorization": f"Bearer {sdk_key}", "X-Sandbox-Id": "test_sandbox_node"}
    
    # web_search: allowed
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_sdk_1", "name": "web_search", "input": {"query": "test"}
    }, headers=headers_sdk)
    assert res.status_code == 200
    # Authorization must allow the capability. The provider may be unavailable
    # in an offline test environment, in which case a structured provider error
    # is acceptable but must not be an authorization denial.
    assert "AUTH::ACCESS_DENIED" not in res.json().get("content", "")

    # shell_exec: denied (requires admin/orch)
    res = await client.post("/v1/orchestrate", json={
        "type": "tool_use", "id": "t_sdk_2", "name": "shell_exec", "input": {"command": "ls"}
    }, headers=headers_sdk)
    assert res.status_code == 200
    assert res.json()["is_error"] is True
    assert "ADMIN privileges" in res.json()["content"]


@pytest.mark.asyncio
async def test_verify_token_caching_and_invalidation(auth_service, db_service):
    # Create a key
    key_data = auth_service.create_api_key("Cache test", token_type="WEB")
    plaintext_token = key_data["token"]
    key_id = key_data["key_id"]
    hashed = hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()

    # 1. Verify token once to populate cache
    identity1 = auth_service.verify_token(plaintext_token)
    assert identity1 is not None
    assert identity1["role"] == "WEB"

    # 2. Delete the token from the database directly (bypassing normal flow)
    db_service.execute("DELETE FROM api_keys WHERE token = ?", (hashed,))

    # 3. verify_token should STILL succeed because it's served from the in-memory cache (TTL < 10s)
    identity2 = auth_service.verify_token(plaintext_token)
    assert identity2 is not None
    assert identity2["role"] == "WEB"

    # 4. Re-insert to test formal revocation eviction
    db_service.execute(
        """
        INSERT INTO api_keys (token, key_id, display_name, token_type, created_at, expires_at, status, masked_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (hashed, key_id, "Cache test", "WEB", "2026-07-05T12:00:00", None, "active", "td_web_••••••••")
    )
    
    # Re-verify to cache
    identity3 = auth_service.verify_token(plaintext_token)
    assert identity3 is not None
    
    # Revoke key (which triggers cache invalidation)
    auth_service.revoke_api_key(key_id)
    
    # verify_token should now immediately fail (evicted from cache)
    identity4 = auth_service.verify_token(plaintext_token)
    assert identity4 is None
