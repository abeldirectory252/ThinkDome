"""Tests for the LLM Orchestrator endpoint, authentication, and Docker executor 6-layer configuration."""

import pytest
import json
from thinkdome.executors.python_docker import PythonDockerExecutor
from thinkdome.executors.base import ExecRequest
from thinkdome.core.config import Settings


@pytest.fixture
def api_keys(app):
    """Fixture to generate test API keys for LLM and ADMIN roles."""
    auth_svc = app.state.auth_service
    llm_key = auth_svc.create_api_key("LLM Test Key", token_type="LLM")
    admin_key = auth_svc.create_api_key("Admin Test Key", token_type="ADMIN")
    
    # Pre-seed active sandboxes to pass the active sandbox validation
    app.state.db_service.create_sandbox(
        sandbox_id="default_admin_sandbox",
        name="Admin Test Env",
        owner="admin",
        memory_mb=256,
        cpu_cores=1.0,
        timeout_sec=30,
        network_enabled=False,
        cost_per_hour=0.02
    )
    app.state.db_service.create_sandbox(
        sandbox_id="default_api_client_sandbox",
        name="API Test Env",
        owner="api_key_client",
        memory_mb=256,
        cpu_cores=1.0,
        timeout_sec=30,
        network_enabled=False,
        cost_per_hour=0.02
    )
    
    return {
        "LLM": llm_key["token"],
        "ADMIN": admin_key["token"]
    }


@pytest.mark.asyncio
async def test_orchestrate_run_code_success(client, api_keys):
    # Valid request with ADMIN token
    payload = {
        "type": "tool_use",
        "id": "toolu_run_code_test_1",
        "name": "run_code",
        "input": {
            "code": "print('Hello Orchestrator!')",
            "language": "python"
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "tool_result"
    assert data["tool_use_id"] == "toolu_run_code_test_1"
    assert data["is_error"] is False
    
    content = json.loads(data["content"])
    assert "Hello Orchestrator!" in content["stdout"]
    assert content["exit_code"] == 0


@pytest.mark.asyncio
async def test_orchestrate_run_code_llm_role(client, api_keys):
    # Valid request with LLM token (should run, but uses LLM limits under the hood)
    payload = {
        "type": "tool_use",
        "id": "toolu_llm_run",
        "name": "run_code",
        "input": {
            "code": "print('Run with LLM token')",
            "language": "python"
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is False
    content = json.loads(data["content"])
    assert "Run with LLM token" in content["stdout"]


@pytest.mark.asyncio
async def test_orchestrate_privilege_denied(client, api_keys):
    # LLM role attempting to call an ADMIN-only tool (write_file)
    payload = {
        "type": "tool_use",
        "id": "toolu_denied_write",
        "name": "write_file",
        "input": {
            "path": "secret.txt",
            "content": "malicious content"
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is True
    assert "Access denied: Tool 'write_file' requires ADMIN privileges" in data["content"]


@pytest.mark.asyncio
async def test_orchestrate_validation_failure(client, api_keys):
    # Invalid tool name (not in enum)
    payload = {
        "type": "tool_use",
        "id": "toolu_invalid",
        "name": "delete_all_files",
        "input": {
            "path": "/"
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert "Validation failed" in data["error"]["message"]


@pytest.mark.asyncio
async def test_orchestrate_run_code_with_security_profile_and_env(client, api_keys):
    # Test that run_code supports security_profile and env_vars in the schema
    payload = {
        "type": "tool_use",
        "id": "toolu_secure_run",
        "name": "run_code",
        "input": {
            "code": "import os; print(os.environ.get('ORCHESTRATOR_ENV'))",
            "language": "python",
            "security_profile": "HIGH_SECURITY",
            "env_vars": {
                "ORCHESTRATOR_ENV": "validated_via_jsonschema"
            }
        }
    }
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is False
    
    content = json.loads(data["content"])
    assert content["stdout"].strip() == "validated_via_jsonschema"


def test_docker_executor_config_llm_role():
    """Unit test for Layer 1 to 6 container configuration built for LLM role."""
    settings = Settings()
    executor = PythonDockerExecutor(settings)
    
    # LLM request
    req = ExecRequest(
        code="print('test')",
        caller_role="LLM",
        allow_network=True # attempt to request network
    )
    
    config = executor._build_container_config(req)
    
    # Layer 1: OS Virtualization (Non-root user)
    assert config["user"] == "1000:1000"
    
    # Layer 2: Filesystem Isolation (Read-only root, tmpfs mounts)
    assert config["read_only"] is True
    assert "/workspace" in config["tmpfs"]
    assert "noexec" in config["tmpfs"]["/workspace"]
    
    # Layer 4: Resource Limits (0.5 CPU, 256MB memory, 20 PIDs)
    assert config["nano_cpus"] == int(0.5 * 1e9)
    assert config["mem_limit"] == "256m"
    assert config["pids_limit"] == 20
    
    # Layer 5: Capability Dropping
    assert config["cap_drop"] == ["ALL"]
    assert config.get("cap_add") is None  # no net capability added
    
    # Layer 6: Network Egress Control (forced none for LLM regardless of request)
    assert config["network_mode"] == "none"
    assert "HTTP_PROXY" not in config["environment"]


def test_docker_executor_config_admin_role():
    """Unit test for Layer 1 to 6 container configuration built for ADMIN role with network."""
    settings = Settings()
    executor = PythonDockerExecutor(settings)
    
    # ADMIN request with network allowed
    req = ExecRequest(
        code="print('test')",
        caller_role="ADMIN",
        allow_network=True
    )
    
    config = executor._build_container_config(req)
    
    # Layer 4: Resource Limits (2.0 CPU, 1024MB memory, 128 PIDs)
    assert config["nano_cpus"] == int(2.0 * 1e9)
    assert config["mem_limit"] == "1024m"
    assert config["pids_limit"] == 128
    
    # Layer 5: NET_BIND_SERVICE capability added since network is enabled
    assert "NET_BIND_SERVICE" in config["cap_add"]
    
    # Layer 6: Egress proxy configuration
    assert config["network_mode"] == "thinkbox-egress"
    assert config["environment"]["HTTP_PROXY"] == "http://thinkbox-proxy:3128"


@pytest.mark.asyncio
async def test_orchestrate_file_utilities(client, api_keys):
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    
    # 1. Create directory using make_dir
    payload = {
        "type": "tool_use",
        "id": "t_mkdir",
        "name": "make_dir",
        "input": {"path": "test_folder"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_error"] is False
    
    # 2. Check if it exists
    payload = {
        "type": "tool_use",
        "id": "t_exists",
        "name": "file_exists",
        "input": {"path": "test_folder"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    res = json.loads(resp.json()["content"])
    assert res["exists"] is True
    assert res["is_dir"] is True

    # 3. Create a file inside utilizing write_file
    payload = {
        "type": "tool_use",
        "id": "t_write",
        "name": "write_file",
        "input": {"path": "test_folder/test.txt", "content": "thinkbox-utility-test"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    
    # 4. Hash the file
    payload = {
        "type": "tool_use",
        "id": "t_hash",
        "name": "hash_file",
        "input": {"path": "test_folder/test.txt", "algorithm": "md5"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    hash_res = json.loads(resp.json()["content"])
    assert "hash" in hash_res
    assert hash_res["algorithm"] == "md5"

    # 5. Clean up by deleting the file
    payload = {
        "type": "tool_use",
        "id": "t_rm",
        "name": "remove_file",
        "input": {"path": "test_folder/test.txt"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    
    # 6. Clean up folder
    payload = {
        "type": "tool_use",
        "id": "t_rmdir",
        "name": "remove_dir",
        "input": {"path": "test_folder"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_orchestrate_memory_tools(client, api_keys):
    """Test memory_store → memory_retrieve → memory_search → memory_list → memory_delete."""
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}

    # 1. Store a memory entry
    payload = {
        "type": "tool_use",
        "id": "t_mem_store",
        "name": "memory_store",
        "input": {"key": "test_key", "content": "This is test knowledge", "tags": ["test", "ci"]}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_error"] is False
    data = json.loads(resp.json()["content"])
    assert data["status"] == "stored"

    # 2. Retrieve the memory entry
    payload = {
        "type": "tool_use",
        "id": "t_mem_get",
        "name": "memory_retrieve",
        "input": {"key": "test_key"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    entry = json.loads(resp.json()["content"])
    assert entry["key"] == "test_key"
    assert "test knowledge" in entry["content"]

    # 3. Search memory
    payload = {
        "type": "tool_use",
        "id": "t_mem_search",
        "name": "memory_search",
        "input": {"query": "knowledge", "tags": ["test"]}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    search_res = json.loads(resp.json()["content"])
    assert search_res["count"] >= 1

    # 4. List memory keys
    payload = {
        "type": "tool_use",
        "id": "t_mem_list",
        "name": "memory_list",
        "input": {"tags": ["ci"]}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    list_res = json.loads(resp.json()["content"])
    assert list_res["count"] >= 1

    # 5. Delete the entry (ADMIN only)
    payload = {
        "type": "tool_use",
        "id": "t_mem_del",
        "name": "memory_delete",
        "input": {"key": "test_key"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    del_res = json.loads(resp.json()["content"])
    assert del_res["status"] == "deleted"


@pytest.mark.asyncio
async def test_orchestrate_shell_exec(client, api_keys):
    """Test shell_exec executes a command and returns stdout."""
    headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    payload = {
        "type": "tool_use",
        "id": "t_shell",
        "name": "shell_exec",
        "input": {"command": "echo hello-thinkbox"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is False
    result = json.loads(data["content"])
    assert "hello-thinkbox" in result["stdout"]
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_orchestrate_shell_exec_denied_for_llm(client, api_keys):
    """Test that LLM tokens cannot execute shell commands."""
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    payload = {
        "type": "tool_use",
        "id": "t_shell_denied",
        "name": "shell_exec",
        "input": {"command": "whoami"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is True
    assert "ADMIN privileges" in data["content"]


@pytest.mark.asyncio
async def test_orchestrate_send_email_denied_for_llm(client, api_keys):
    """Test that LLM tokens cannot send emails."""
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    payload = {
        "type": "tool_use",
        "id": "t_email_denied",
        "name": "send_email",
        "input": {"to": "test@test.com", "subject": "test", "body": "test"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is True
    assert "ADMIN privileges" in data["content"]


@pytest.mark.asyncio
async def test_orchestrate_send_telegram_denied_for_llm(client, api_keys):
    """Test that LLM tokens cannot send Telegram messages."""
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    payload = {
        "type": "tool_use",
        "id": "t_tg_denied",
        "name": "send_telegram",
        "input": {"chat_id": "12345", "message": "test"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is True
    assert "ADMIN privileges" in data["content"]


@pytest.mark.asyncio
async def test_orchestrate_http_request_denied_for_llm(client, api_keys):
    """Test that LLM tokens cannot make HTTP requests."""
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}
    payload = {
        "type": "tool_use",
        "id": "t_http_denied",
        "name": "http_request",
        "input": {"url": "https://example.com"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_error"] is True
    assert "ADMIN privileges" in data["content"]


@pytest.mark.asyncio
async def test_orchestrate_memory_store_allowed_for_llm(client, api_keys):
    """Test that LLM tokens CAN store and search memory (read/write knowledge is allowed)."""
    headers = {"Authorization": f"Bearer {api_keys['LLM']}"}

    # Store
    payload = {
        "type": "tool_use",
        "id": "t_llm_mem",
        "name": "memory_store",
        "input": {"key": "llm_note", "content": "LLM can store notes"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_error"] is False

    # Search
    payload = {
        "type": "tool_use",
        "id": "t_llm_mem_search",
        "name": "memory_search",
        "input": {"query": "LLM"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_error"] is False

    # But delete is ADMIN only
    payload = {
        "type": "tool_use",
        "id": "t_llm_mem_del",
        "name": "memory_delete",
        "input": {"key": "llm_note"}
    }
    resp = await client.post("/v1/orchestrate", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_error"] is True
    assert "ADMIN privileges" in resp.json()["content"]

    # Clean up with admin
    admin_headers = {"Authorization": f"Bearer {api_keys['ADMIN']}"}
    payload["id"] = "t_admin_cleanup"
    resp = await client.post("/v1/orchestrate", json=payload, headers=admin_headers)
    assert resp.status_code == 200
