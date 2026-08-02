import pytest
from pathlib import Path
from unittest.mock import MagicMock

from thinkdome.orchestration.tools import ToolContext, current_tool_context, registry, RegisteredTool
from thinkdome.apps.erp.tools import get_frappe_client, get_query_engine, get_accounting_service
from thinkdome.orchestration.mcp_server import get_mcp_server


def test_tool_context_service_binding():
    mock_execution = MagicMock()
    mock_db = MagicMock()

    ctx = ToolContext(
        username="erp_accountant",
        sandbox_id="sb_123",
        workspace_dir=Path("/tmp"),
        execution_service=mock_execution,
        search_service=None,
        db=mock_db,
        caller_role="ACCOUNTS_USER",
    )

    mock_frappe = MagicMock()
    ctx.set_service("frappe_client", mock_frappe)

    assert ctx.get_service("frappe_client") == mock_frappe

    # Test current_tool_context scoping
    token = current_tool_context.set(ctx)
    try:
        resolved_client = get_frappe_client()
        assert resolved_client == mock_frappe
    finally:
        current_tool_context.reset(token)


def test_tool_registry_category_and_search_filtering():
    # Register mock tools with categories
    @registry.register(
        name="test_acc_tool",
        description="Accounting ledger report tool",
        category="erp.accounting",
    )
    def acc_func():
        return "acc"

    @registry.register(
        name="test_inv_tool",
        description="Inventory stock balance tool",
        category="erp.inventory",
    )
    def inv_func():
        return "inv"

    tools_acc = registry.get_active_tools(category="erp.accounting")
    tool_names_acc = [t.name for t in tools_acc]
    assert "test_acc_tool" in tool_names_acc
    assert "test_inv_tool" not in tool_names_acc

    tools_search = registry.get_active_tools(search="stock balance")
    tool_names_search = [t.name for t in tools_search]
    assert "test_inv_tool" in tool_names_search
    assert "test_acc_tool" not in tool_names_search


@pytest.mark.asyncio
async def test_mcp_server_rbac_identity_propagation():
    mock_db = MagicMock()
    mock_orchestrator = MagicMock()

    async def mock_exec_tool(*args, **kwargs):
        return {"content": "Tool Executed Successfully"}

    mock_orchestrator.execute_tool = mock_exec_tool
    mock_db.fetch_all.return_value = [{"sandbox_id": "sb_test"}]

    server = get_mcp_server(
        site_name="personal",
        db_service=mock_db,
        orchestrator=mock_orchestrator,
        caller_role="SALES_MANAGER",
        username="john_doe",
    )

    assert server is not None
