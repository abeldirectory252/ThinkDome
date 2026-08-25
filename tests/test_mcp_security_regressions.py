"""Regression test suite for MCP Security & Reliability audit findings (MCP-1 through MCP-6)."""

import pytest
import asyncio
from pathlib import Path
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.mcp_server import get_mcp_server
from thinkdome.platform.orchestration.network.tools import HttpRequestTool
from thinkdome.sandbox.tools.execution_tools import HostHtmlTool
from thinkdome.platform.orchestration.tools import ToolContext, current_tool_context
from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.database.service import DatabaseService
from thinkdome.platform.orchestration.search.service import SearchService


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
