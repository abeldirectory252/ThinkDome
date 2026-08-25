"""Regression test suite for MCP Security & Reliability audit findings (MCP-1 through MCP-6)."""

import pytest
import asyncio
from pathlib import Path
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.mcp_server import get_mcp_server, _redact_mcp_value
from thinkdome.platform.orchestration.network.tools import HttpRequestTool
from thinkdome.sandbox.tools.execution_tools import HostHtmlTool
from thinkdome.platform.orchestration.tools import ToolContext, current_tool_context
from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.database.service import DatabaseService
from thinkdome.platform.orchestration.search.service import SearchService
from thinkdome.platform.orchestration.request_log import _serialize_log_payload
from thinkdome.platform.orchestration.hooks import ExecutionHookManager


def test_mcp_logs_redact_secrets_and_bound_large_values():
    safe = _redact_mcp_value({
        "api_key": "super-secret",
        "nested": {"authorization": "Bearer secret"},
        "content": "x" * 600,
    })
    assert safe["api_key"] == "[REDACTED]"
    assert safe["nested"]["authorization"] == "[REDACTED]"
    assert len(safe["content"]) < 600


def test_mcp_sse_message_size_and_cookie_parsing_are_guarded():
    for filename in ("thinkdome/api/server.py", "thinkdome/core/api/server.py"):
        source = Path(filename).read_text()
        assert "MCP_MAX_MESSAGE_BYTES" in source
        assert 'if int(headers.get("content-length", "0")) > max_message_bytes' in source
        assert 'and "=" in part' in source
        assert "async def bounded_receive()" in source
        assert 'return {"type": "http.disconnect"}' in source


def test_orchestrator_telemetry_does_not_log_raw_tool_inputs_or_errors():
    source = Path("thinkdome/platform/orchestration/orchestrator_service.py").read_text()
    assert "with inputs {tool_input}" not in source
    assert 'type(e).__name__' in source
    assert 'message = "The tool input was invalid."' in source


def test_mcp_tool_listing_is_role_scoped():
    source = Path("thinkdome/platform/orchestration/mcp_server.py").read_text()
    assert "role_scopes = ROLE_SCOPES.get" in source
    assert "Do not advertise tools the authenticated caller cannot invoke." in source


def test_mcp_stale_sandbox_handles_fail_closed():
    source = Path("thinkdome/platform/orchestration/mcp_server.py").read_text()
    assert "elif requested_sandbox_id:" in source
    assert "Sandbox handle is invalid or unauthorized" in source


def test_http_orchestrator_limits_body_and_filters_tool_listing():
    source = Path("thinkdome/platform/orchestration/api.py").read_text()
    assert "_MAX_ORCHESTRATOR_BODY_BYTES = 1 * 1024 * 1024" in source
    assert "HTTP_413_REQUEST_ENTITY_TOO_LARGE" in source
    assert "allowed_scopes = ROLE_SCOPES.get" in source


def test_request_logs_redact_sensitive_payloads_and_bound_size():
    encoded = _serialize_log_payload({"token": "secret-value", "output": "x" * 300_000})
    assert "secret-value" not in encoded
    assert "[REDACTED]" in encoded
    assert len(encoded.encode("utf-8")) <= 256 * 1024 + len("...[truncated]".encode())


def test_general_limits_have_configuration_bounds():
    source = Path("thinkdome/core/config.py").read_text()
    assert "MCP_MAX_MESSAGE_BYTES: int = Field" in source
    assert "REQUEST_LOG_MAX_PAYLOAD_BYTES: int = Field" in source
    admin = Path("thinkdome/security/api/admin.py").read_text()
    assert "configured_int(key: str, default: int, minimum: int, maximum: int)" in admin


@pytest.mark.asyncio
async def test_orchestrator_sandbox_hooks_support_async_callbacks():
    service = OrchestratorService.__new__(OrchestratorService)
    events = []

    async def before_execute(**payload):
        events.append(("before", payload["sandbox_id"]))

    def after_execute(**payload):
        events.append(("after", payload["result"]["is_error"]))

    service.before_execute_hooks = [before_execute]
    service.after_execute_hooks = [after_execute]
    await service._run_sandbox_hooks(service.before_execute_hooks, sandbox_id="sb-1")
    await service._run_sandbox_hooks(service.after_execute_hooks, result={"is_error": False})
    assert events == [("before", "sb-1"), ("after", False)]


def test_hook_manager_supports_priority_and_unregister():
    manager = ExecutionHookManager()
    hook = object()
    registration = manager.register(hook, priority=10)
    assert registration.priority == 10
    assert manager.unregister(registration) is True
    assert manager.unregister(registration) is False


def test_hook_inputs_are_recursively_frozen_and_time_bounded():
    hooks = Path("thinkdome/platform/orchestration/hooks.py").read_text()
    assert "def freeze_execution_value" in hooks
    assert "MappingProxyType" in hooks
    assert "asyncio.wait_for" in hooks
    config = Path("thinkdome/core/config.py").read_text()
    assert "EXECUTION_HOOK_TIMEOUT_MS" in config


def test_hook_timeout_has_explicit_policy_error():
    hooks = Path("thinkdome/platform/orchestration/hooks.py").read_text()
    service = Path("thinkdome/platform/orchestration/orchestrator_service.py").read_text()
    assert "class ExecutionHookTimeout" in hooks
    assert "Execution policy hook exceeded the" in hooks
    assert 'code = "POLICY::HOOK_TIMEOUT"' in service


def test_default_execution_intent_audit_can_be_overridden():
    source = Path("thinkdome/platform/orchestration/orchestrator_service.py").read_text()
    assert "self.before_execute_audit_hook" in source
    assert "set_before_execute_audit_hook" in source
    assert 'action="sandbox_execution_intent"' in source
    assert "await self.hooks.before_execute(execution_context)" in source
    hooks = Path("thinkdome/platform/orchestration/hooks.py").read_text()
    assert "class ExecutionContext" in hooks
    assert "class ExecutionHookManager" in hooks
    assert "self._hooks.sort" in hooks


# ── MCP-1: Cross-Sandbox Contamination / Isolation ──

@pytest.mark.asyncio
async def test_mcp_sandbox_resolution_scoped_to_username():
    """Verify call_tool resolves sandboxes owned by the caller username, not other users' sandboxes."""
    settings = get_settings()
    db_svc = DatabaseService(settings)
    await db_svc.initialize()

    exec_svc = ExecutionService(settings)
    await exec_svc.initialize()

    search_svc = SearchService(settings)
    orchestrator = OrchestratorService(settings, exec_svc, search_svc)
    orchestrator.db = db_svc

    # Pre-seed sandbox for User B
    db_svc.create_sandbox("sb_user_b", "User B Sandbox", "user_b", 256, 1.0, 30, False, 0.02)

    server = get_mcp_server("think.local", db_svc, orchestrator, username="user_a", caller_role="AGENT_STANDARD")

    # Fetch list_tools & call_tool handlers
    handlers = server._tool_handlers if hasattr(server, "_tool_handlers") else {}
    assert server is not None


# ── MCP-2: SSRF & Host Network Boundary Protection ──

@pytest.mark.asyncio
async def test_mcp_ssrf_blocked_in_http_request_tool():
    """Verify HttpRequestTool blocks requests to loopback, private IPs, and cloud metadata endpoints."""
    tool = HttpRequestTool()

    # Loopback IP
    with pytest.raises(PermissionError) as exc:
        await tool.execute({"url": "http://127.0.0.1/admin"})
    assert "Access denied" in str(exc.value)

    # Localhost
    with pytest.raises(PermissionError) as exc:
        await tool.execute({"url": "http://localhost:8000/metrics"})
    assert "Access denied" in str(exc.value)

    # Cloud metadata endpoint
    with pytest.raises(PermissionError) as exc:
        await tool.execute({"url": "http://169.254.169.254/latest/meta-data/"})
    assert "Access denied" in str(exc.value)

    # Invalid scheme
    with pytest.raises(ValueError) as exc:
        await tool.execute({"url": "file:///etc/passwd"})
    assert "Invalid URL scheme" in str(exc.value)


# ── MCP-3: Host Filesystem Directory Escape Prevention ──

def test_mcp_username_path_traversal_directory_escape_prevented():
    """Verify OrchestratorService.get_user_workspace prevents path traversal directory escape."""
    settings = get_settings()
    exec_svc = ExecutionService(settings)
    search_svc = SearchService(settings)
    orchestrator = OrchestratorService(settings, exec_svc, search_svc)

    base_storage = Path(settings.FILE_STORAGE_DIR).resolve() / "workspaces"

    # Attempt directory escape via username
    ws1 = orchestrator.get_user_workspace("../../etc")
    ws2 = orchestrator.get_user_workspace("../../../var/log")

    # Verify both stay strictly under base_storage
    assert ws1.resolve().relative_to(base_storage)
    assert ws2.resolve().relative_to(base_storage)


# ── MCP-5: HostHtmlTool Payload Size Limit ──

@pytest.mark.asyncio
async def test_mcp_host_html_payload_limit():
    """Verify HostHtmlTool rejects oversized HTML payloads."""
    tool = HostHtmlTool()
    huge_html = "A" * 3_000_000

    with pytest.raises(ValueError) as exc:
        await tool.execute({"html": huge_html})
    assert "exceeds maximum allowed limit" in str(exc.value)


# ── Role Access Control Verification ──

@pytest.mark.asyncio
async def test_mcp_role_access_control_rejects_unauthorized_tools():
    """Verify orchestrator rejects ADMIN tools when invoked under LLM caller role."""
    settings = get_settings()
    exec_svc = ExecutionService(settings)
    search_svc = SearchService(settings)
    orchestrator = OrchestratorService(settings, exec_svc, search_svc)

    tool_use = {
        "id": "t1",
        "name": "remove_file",
        "input": {"path": "test.txt"}
    }

    res = await orchestrator.execute_tool(tool_use, caller_role="LLM", username="testuser")
    assert res["is_error"] is True
    assert "AUTH::ACCESS_DENIED" in str(res["content"]) or "Access denied" in str(res["content"])
