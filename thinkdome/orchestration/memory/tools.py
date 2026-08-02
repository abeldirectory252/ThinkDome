import json
from pathlib import Path
from typing import Any
from thinkdome.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.orchestration.orchestrator_models import (
    MemoryStoreInput, MemoryRetrieveInput, MemorySearchInput, MemoryDeleteInput, MemoryListInput
)

def _get_memory_store_path(workspace_dir: Path) -> Path:
    """Return the path to the JSON-backed memory store."""
    store_path = workspace_dir / ".thinkbox" / "memory"
    store_path.mkdir(parents=True, exist_ok=True)
    return store_path


def _load_memory_index(workspace_dir: Path) -> dict:
    """Load the memory index from disk."""
    index_path = _get_memory_store_path(workspace_dir) / "_index.json"
    if index_path.exists():
        return json.loads(index_path.read_text(encoding="utf-8"))
    return {}


def _save_memory_index(workspace_dir: Path, index: dict) -> None:
    """Save the memory index to disk."""
    index_path = _get_memory_store_path(workspace_dir) / "_index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


@register_tool
class MemoryStoreTool(BaseTool):
    name = "memory_store"
    description = "Store a key-value entry in persistent memory"
    required_scope = "memory:write"
    input_schema = MemoryStoreInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        key = tool_input.get("key")
        content = tool_input.get("content")
        tags = tool_input.get("tags", [])
        if not key or content is None:
            raise ValueError("Parameters 'key' and 'content' are required for memory_store.")

        ctx = get_context()
        store_path = _get_memory_store_path(ctx.workspace_dir)

        # Save content file
        safe_key = key.replace("/", "_").replace("\\", "_").replace("..", "_")
        entry_path = store_path / f"{safe_key}.json"
        entry = {
            "key": key,
            "content": content,
            "tags": tags or [],
            "created_at": __import__("time").time(),
        }
        entry_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")

        # Update index
        index = _load_memory_index(ctx.workspace_dir)
        index[key] = {"tags": tags or [], "file": f"{safe_key}.json"}
        _save_memory_index(ctx.workspace_dir, index)

        return json.dumps({"status": "stored", "key": key})


@register_tool
class MemoryRetrieveTool(BaseTool):
    name = "memory_retrieve"
    description = "Retrieve a specific memory entry by key"
    required_scope = "memory:read"
    input_schema = MemoryRetrieveInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        key = tool_input.get("key")
        if not key:
            raise ValueError("Parameter 'key' is required for memory_retrieve.")

        ctx = get_context()
        index = _load_memory_index(ctx.workspace_dir)
        if key not in index:
            raise FileNotFoundError(f"Memory key not found: {key}")

        store_path = _get_memory_store_path(ctx.workspace_dir)
        entry_path = store_path / index[key]["file"]
        if not entry_path.exists():
            raise FileNotFoundError(f"Memory file missing for key: {key}")

        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        return json.dumps(entry, indent=2)


@register_tool
class MemorySearchTool(BaseTool):
    name = "memory_search"
    description = "Search memory entries by query and optional tags"
    required_scope = "memory:read"
    input_schema = MemorySearchInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        query = tool_input.get("query", "").lower()
        limit = tool_input.get("limit", 10)
        filter_tags = tool_input.get("tags", [])

        if not query:
            raise ValueError("Parameter 'query' is required for memory_search.")

        ctx = get_context()
        store_path = _get_memory_store_path(ctx.workspace_dir)
        index = _load_memory_index(ctx.workspace_dir)
        results = []

        for key, meta in index.items():
            # Tag filter
            if filter_tags:
                if not set(filter_tags).intersection(set(meta.get("tags", []))):
                    continue

            entry_path = store_path / meta["file"]
            if not entry_path.exists():
                continue

            entry = json.loads(entry_path.read_text(encoding="utf-8"))
            content = entry.get("content", "")

            # Simple substring search across key and content
            if query in key.lower() or query in content.lower():
                results.append({
                    "key": key,
                    "content": content[:500],  # truncate preview
                    "tags": entry.get("tags", []),
                })

            if len(results) >= limit:
                break

        return json.dumps({"query": query, "count": len(results), "results": results}, indent=2)


@register_tool
class MemoryDeleteTool(BaseTool):
    name = "memory_delete"
    description = "Delete a memory entry by key"
    required_scope = "memory:delete"
    input_schema = MemoryDeleteInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        key = tool_input.get("key")
        if not key:
            raise ValueError("Parameter 'key' is required for memory_delete.")

        ctx = get_context()
        index = _load_memory_index(ctx.workspace_dir)
        if key not in index:
            raise FileNotFoundError(f"Memory key not found: {key}")

        store_path = _get_memory_store_path(ctx.workspace_dir)
        entry_path = store_path / index[key]["file"]
        if entry_path.exists():
            entry_path.unlink()

        del index[key]
        _save_memory_index(ctx.workspace_dir, index)

        return json.dumps({"status": "deleted", "key": key})


@register_tool
class MemoryListTool(BaseTool):
    name = "memory_list"
    description = "List all memory keys, optionally filtered by tags"
    required_scope = "memory:read"
    input_schema = MemoryListInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        filter_tags = tool_input.get("tags", [])
        limit = tool_input.get("limit", 50)

        ctx = get_context()
        index = _load_memory_index(ctx.workspace_dir)
        keys = []

        for key, meta in index.items():
            if filter_tags:
                if not set(filter_tags).intersection(set(meta.get("tags", []))):
                    continue
            keys.append({"key": key, "tags": meta.get("tags", [])})
            if len(keys) >= limit:
                break

        return json.dumps({"count": len(keys), "keys": keys}, indent=2)
