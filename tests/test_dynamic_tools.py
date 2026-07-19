"""Tests for dynamic tool registry and decorators."""

import pytest
from pydantic import BaseModel, Field

from thinkdome.core.tools import think_tool, registry, ToolContext


# ── Helper tools (NOT test functions — prefixed with _ to avoid pytest collection) ──

class CustomToolInput(BaseModel):
    arg1: str = Field(..., description="First custom arg")
    arg2: int = Field(default=42, description="Second custom arg")


@think_tool(name="test_custom_info", description="Retrieve test custom info", required_scope="file:read", input_schema=CustomToolInput)
async def _custom_info_tool(arg1: str, arg2: int = 42) -> str:
    return f"arg1: {arg1}, arg2: {arg2}"


@think_tool(name="test_reflection_tool", description="Test auto-generated schema using reflection")
def _reflection_tool(message: str, count: int) -> str:
    return f"msg: {message}, count: {count}"


# ── Actual tests ──

@pytest.mark.asyncio
async def test_tool_registration_metadata():
    tool = registry.get_tool("test_custom_info")
    assert tool is not None
    assert tool.name == "test_custom_info"
    assert tool.description == "Retrieve test custom info"
    assert tool.required_scope == "file:read"
    assert tool.app_name == "core"
    assert "arg1" in tool.input_schema["properties"]
    assert "arg2" in tool.input_schema["properties"]


@pytest.mark.asyncio
async def test_reflection_schema_generation():
    tool = registry.get_tool("test_reflection_tool")
    assert tool is not None
    assert tool.input_schema["type"] == "object"
    assert "message" in tool.input_schema["properties"]
    assert "count" in tool.input_schema["properties"]
    assert "message" in tool.input_schema["required"]
    assert "count" in tool.input_schema["required"]


@pytest.mark.asyncio
async def test_core_tools_registered():
    """Verify that all 24 core tools are registered."""
    expected = [
        "read_file", "write_file", "list_dir", "file_exists", "make_dir",
        "remove_file", "remove_dir", "move_file", "copy_file",
        "run_code", "web_search", "grep_search", "find_files",
        "get_file_info", "hash_file", "http_request",
        "memory_store", "memory_retrieve", "memory_search",
        "memory_delete", "memory_list",
        "shell_exec", "send_email", "send_telegram",
    ]
    for name in expected:
        tool = registry.get_tool(name)
        assert tool is not None, f"Tool '{name}' not registered"
        assert tool.input_schema is not None, f"Tool '{name}' missing input_schema"


@pytest.mark.asyncio
async def test_list_all_tools():
    all_tools = registry.list_all_tools()
    assert len(all_tools) >= 24
    names = {t.name for t in all_tools}
    assert "run_code" in names
    assert "read_file" in names
    assert "shell_exec" in names
