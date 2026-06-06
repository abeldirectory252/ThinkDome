"""Orchestrator service for executing LLM-like tool use requests."""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any, Optional
import jsonschema

from thinkdome.core.config import Settings
from thinkdome.services.execution_service import ExecutionService
from thinkdome.services.search_service import SearchService
from thinkdome.models.execution import ExecuteRequest
from thinkdome.models.search import SearchRequest

logger = logging.getLogger(__name__)

class OrchestratorService:
    """Validates and executes tool use blocks like an LLM orchestrator."""

    def __init__(
        self,
        settings: Settings,
        execution_service: ExecutionService,
        search_service: SearchService,
    ) -> None:
        self.settings = settings
        self.execution_service = execution_service
        self.search_service = search_service
        
        # Set workspace root to the project root directory
        self.workspace_root = Path(__file__).resolve().parents[2]
        logger.info(f"OrchestratorService initialized with workspace root: {self.workspace_root}")

    def validate_request(self, data: dict) -> None:
        """Validate request against Pydantic Python schema."""
        from thinkdome.models.orchestrator import ToolUseRequest
        from pydantic import ValidationError

        try:
            req = ToolUseRequest.model_validate(data)
            req.validate_input()
        except ValidationError as e:
            error_msgs = []
            for err in e.errors():
                loc = " -> ".join(str(l) for l in err.get("loc", []))
                msg = err.get("msg", "Invalid value")
                error_msgs.append(f"{loc}: {msg}" if loc else msg)
            raise ValueError(f"Validation failed: {'; '.join(error_msgs)}")
        except Exception as e:
            raise ValueError(str(e))

    def _resolve_safe_path(self, path_str: str) -> Path:
        """Resolve path and ensure it remains within the workspace root directory."""
        # Clean leading slashes and drive letters
        cleaned = path_str.lstrip("/\\")
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].lstrip("/\\")
        
        target_path = Path(os.path.abspath(self.workspace_root / cleaned))
        try:
            target_path.relative_to(self.workspace_root)
        except ValueError:
            raise PermissionError(f"Access denied: path '{path_str}' escapes workspace boundaries.")
        return target_path

    async def execute_tool(self, tool_use: dict, caller_role: str = "LLM", sandbox_limits: Optional[dict] = None) -> dict:
        """Execute a tool use request and return a tool result block."""
        tool_id = tool_use["id"]
        tool_name = tool_use["name"]
        tool_input = tool_use["input"]

        logger.info(f"Executing tool {tool_name} (id: {tool_id}) with inputs {tool_input} (caller: {caller_role})")
        
        try:
            # â”€â”€ PRIVILEGE VERIFICATION â”€â”€
            # Destructive file ops + shell + communication = ADMIN only
            ADMIN_ONLY_TOOLS = {
                "write_file", "make_dir", "remove_file", "remove_dir",
                "move_file", "copy_file", "shell_exec",
                "send_email", "send_telegram",
                "memory_delete",
            }
            # Network-touching tools require ADMIN unless run_code handles it internally
            ADMIN_NETWORK_TOOLS = {"http_request"}

            if tool_name in ADMIN_ONLY_TOOLS and (caller_role or "LLM").upper() != "ADMIN":
                raise PermissionError(f"Access denied: Tool '{tool_name}' requires ADMIN privileges.")
            if tool_name in ADMIN_NETWORK_TOOLS and (caller_role or "LLM").upper() != "ADMIN":
                raise PermissionError(
                    f"Access denied: Tool '{tool_name}' requires ADMIN privileges (network access)."
                )

            # â”€â”€ TOOL DISPATCH â”€â”€
            if tool_name == "read_file":
                result_content = await self._tool_read_file(tool_input)
            elif tool_name == "write_file":
                result_content = await self._tool_write_file(tool_input)
            elif tool_name == "run_code":
                result_content = await self._tool_run_code(tool_input, caller_role, sandbox_limits)
            elif tool_name == "list_dir":
                result_content = await self._tool_list_dir(tool_input)
            elif tool_name == "web_search":
                result_content = await self._tool_web_search(tool_input)
            elif tool_name == "file_exists":
                result_content = await self._tool_file_exists(tool_input)
            elif tool_name == "make_dir":
                result_content = await self._tool_make_dir(tool_input)
            elif tool_name == "remove_file":
                result_content = await self._tool_remove_file(tool_input)
            elif tool_name == "remove_dir":
                result_content = await self._tool_remove_dir(tool_input)
            elif tool_name == "move_file":
                result_content = await self._tool_move_file(tool_input)
            elif tool_name == "copy_file":
                result_content = await self._tool_copy_file(tool_input)
            elif tool_name == "grep_search":
                result_content = await self._tool_grep_search(tool_input)
            elif tool_name == "find_files":
                result_content = await self._tool_find_files(tool_input)
            elif tool_name == "get_file_info":
                result_content = await self._tool_get_file_info(tool_input)
            elif tool_name == "hash_file":
                result_content = await self._tool_hash_file(tool_input)
            # â”€â”€ API / HTTP â”€â”€
            elif tool_name == "http_request":
                result_content = await self._tool_http_request(tool_input)
            # â”€â”€ Memory & Knowledge â”€â”€
            elif tool_name == "memory_store":
                result_content = await self._tool_memory_store(tool_input)
            elif tool_name == "memory_retrieve":
                result_content = await self._tool_memory_retrieve(tool_input)
            elif tool_name == "memory_search":
                result_content = await self._tool_memory_search(tool_input)
            elif tool_name == "memory_delete":
                result_content = await self._tool_memory_delete(tool_input)
            elif tool_name == "memory_list":
                result_content = await self._tool_memory_list(tool_input)
            # â”€â”€ Shell â”€â”€
            elif tool_name == "shell_exec":
                result_content = await self._tool_shell_exec(tool_input)
            # â”€â”€ Communication â”€â”€
            elif tool_name == "send_email":
                result_content = await self._tool_send_email(tool_input)
            elif tool_name == "send_telegram":
                result_content = await self._tool_send_telegram(tool_input)
            else:
                raise ValueError(f"Unknown tool name: {tool_name}")

            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result_content,
                "is_error": False
            }

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": f"Error executing tool '{tool_name}': {str(e)}",
                "is_error": True
            }

    async def _tool_read_file(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for read_file.")
        
        safe_path = self._resolve_safe_path(tool_input["path"])
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {tool_input['path']}")
        if not safe_path.is_file():
            raise ValueError(f"Path is a directory, not a file: {tool_input['path']}")
        
        # Read content
        try:
            return safe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Fallback to base64 if it's binary
            import base64
            binary_content = safe_path.read_bytes()
            return base64.b64encode(binary_content).decode("utf-8")

    async def _tool_write_file(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for write_file.")
        if "content" not in tool_input:
            raise ValueError("Parameter 'content' is required for write_file.")
        
        safe_path = self._resolve_safe_path(tool_input["path"])
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        
        safe_path.write_text(tool_input["content"], encoding="utf-8")
        return f"Successfully wrote {len(tool_input['content'])} characters to {tool_input['path']}."

    async def _tool_list_dir(self, tool_input: dict[str, Any]) -> str:
        path_str = tool_input.get("path", ".")
        safe_path = self._resolve_safe_path(path_str)
        
        if not safe_path.exists():
            raise FileNotFoundError(f"Directory not found: {path_str}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is a file, not a directory: {path_str}")

        entries = []
        for item in sorted(safe_path.iterdir()):
            rel_path = item.relative_to(self.workspace_root)
            is_directory = item.is_dir()
            size = item.stat().st_size if not is_directory else None
            entries.append({
                "name": item.name,
                "path": str(rel_path),
                "type": "directory" if is_directory else "file",
                "size_bytes": size
            })
        
        return json.dumps(entries, indent=2)

    async def _tool_run_code(self, tool_input: dict[str, Any], caller_role: str = "LLM", sandbox_limits: Optional[dict] = None) -> str:
        if "code" not in tool_input:
            raise ValueError("Parameter 'code' is required for run_code.")
        
        language = tool_input.get("language", "python")
        stdin = tool_input.get("stdin")

        # Enforce sandbox timeout if present
        timeout_ms = 5000
        if sandbox_limits and "timeout_sec" in sandbox_limits:
            timeout_ms = sandbox_limits["timeout_sec"] * 1000

        # Enforce sandbox network enablement if present
        allow_network = tool_input.get("allow_network", False)
        if sandbox_limits and "network_enabled" in sandbox_limits:
            allow_network = bool(sandbox_limits["network_enabled"])

        exec_req = ExecuteRequest(
            code=tool_input["code"],
            language=language,
            stdin=stdin,
            security_profile=tool_input.get("security_profile", "HIGH_SECURITY"),
            env_vars=tool_input.get("env_vars"),
            caller_role=caller_role,
            allow_network=allow_network,
            memory_limit_mb=sandbox_limits.get("memory_mb") if sandbox_limits else None,
            cpu_cores=sandbox_limits.get("cpu_cores") if sandbox_limits else None,
            timeout_ms=timeout_ms,
        )
        
        resp = await self.execution_service.execute(exec_req)
        
        result_dict = {
            "stdout": resp.stdout,
            "stderr": resp.stderr,
            "exit_code": resp.exit_code,
            "timed_out": resp.timed_out,
            "duration_ms": resp.duration_ms
        }
        
        return json.dumps(result_dict, indent=2)

    async def _tool_web_search(self, tool_input: dict[str, Any]) -> str:
        if "query" not in tool_input:
            raise ValueError("Parameter 'query' is required for web_search.")
        
        max_results = tool_input.get("max_results", 10)
        request = SearchRequest(query=tool_input["query"], max_results=max_results)
        
        resp = await self.search_service.search(request)
        
        results_list = []
        for r in resp.results:
            results_list.append(f"Title: {r.title}\nURL: {r.url}\nSnippet: {r.snippet}\n---")
            
        return "\n\n".join(results_list) if results_list else "No results found."

    async def _tool_file_exists(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for file_exists.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        exists = safe_path.exists()
        return json.dumps({
            "path": tool_input["path"],
            "exists": exists,
            "is_file": safe_path.is_file() if exists else False,
            "is_dir": safe_path.is_dir() if exists else False
        })

    async def _tool_make_dir(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for make_dir.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        safe_path.mkdir(parents=True, exist_ok=True)
        return f"Successfully created directory: {tool_input['path']}"

    async def _tool_remove_file(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for remove_file.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {tool_input['path']}")
        if not safe_path.is_file():
            raise ValueError(f"Path is a directory, not a file: {tool_input['path']}")
        safe_path.unlink()
        return f"Successfully removed file: {tool_input['path']}"

    async def _tool_remove_dir(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for remove_dir.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        if not safe_path.exists():
            raise FileNotFoundError(f"Directory not found: {tool_input['path']}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is a file, not a directory: {tool_input['path']}")
        
        import shutil
        shutil.rmtree(safe_path)
        return f"Successfully removed directory: {tool_input['path']}"

    async def _tool_move_file(self, tool_input: dict[str, Any]) -> str:
        if "src" not in tool_input or "dest" not in tool_input:
            raise ValueError("Parameters 'src' and 'dest' are required for move_file.")
        safe_src = self._resolve_safe_path(tool_input["src"])
        safe_dest = self._resolve_safe_path(tool_input["dest"])
        
        if not safe_src.exists():
            raise FileNotFoundError(f"Source path not found: {tool_input['src']}")
            
        safe_dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(safe_src), str(safe_dest))
        return f"Successfully moved {tool_input['src']} to {tool_input['dest']}"

    async def _tool_copy_file(self, tool_input: dict[str, Any]) -> str:
        if "src" not in tool_input or "dest" not in tool_input:
            raise ValueError("Parameters 'src' and 'dest' are required for copy_file.")
        safe_src = self._resolve_safe_path(tool_input["src"])
        safe_dest = self._resolve_safe_path(tool_input["dest"])
        
        if not safe_src.exists():
            raise FileNotFoundError(f"Source path not found: {tool_input['src']}")
        if not safe_src.is_file():
            raise ValueError(f"Source path is a directory, copy_file only supports copying files: {tool_input['src']}")
            
        safe_dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(safe_src), str(safe_dest))
        return f"Successfully copied {tool_input['src']} to {tool_input['dest']}"

    async def _tool_grep_search(self, tool_input: dict[str, Any]) -> str:
        if "pattern" not in tool_input:
            raise ValueError("Parameter 'pattern' is required for grep_search.")
        
        path_str = tool_input.get("path", ".")
        safe_path = self._resolve_safe_path(path_str)
        if not safe_path.exists():
            raise FileNotFoundError(f"Search path not found: {path_str}")
            
        import re
        pattern_str = tool_input["pattern"]
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")
            
        matches = []
        if safe_path.is_file():
            files_to_search = [safe_path]
        else:
            files_to_search = [p for p in safe_path.rglob("*") if p.is_file()]
            
        for fpath in files_to_search:
            if fpath.stat().st_size > 10 * 1024 * 1024:
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                for line_idx, line in enumerate(content.splitlines(), 1):
                    if pattern.search(line):
                        rel_path = fpath.relative_to(self.workspace_root)
                        matches.append({
                            "file": str(rel_path),
                            "line": line_idx,
                            "content": line.strip()
                        })
                        if len(matches) >= 100:
                            break
            except Exception:
                pass
            if len(matches) >= 100:
                break
                
        return json.dumps(matches, indent=2)

    async def _tool_find_files(self, tool_input: dict[str, Any]) -> str:
        if "pattern" not in tool_input:
            raise ValueError("Parameter 'pattern' is required for find_files.")
        
        path_str = tool_input.get("path", ".")
        safe_path = self._resolve_safe_path(path_str)
        if not safe_path.exists():
            raise FileNotFoundError(f"Search path not found: {path_str}")
            
        pattern = tool_input["pattern"]
        matched_files = []
        
        # Determine root of find
        search_root = safe_path if safe_path.is_dir() else safe_path.parent
        for item in search_root.rglob(pattern):
            if item.is_file():
                rel_path = item.relative_to(self.workspace_root)
                matched_files.append(str(rel_path))
                if len(matched_files) >= 500:
                    break
        return json.dumps(matched_files, indent=2)

    async def _tool_get_file_info(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for get_file_info.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        if not safe_path.exists():
            raise FileNotFoundError(f"Path not found: {tool_input['path']}")
            
        stat = safe_path.stat()
        info = {
            "path": tool_input["path"],
            "size_bytes": stat.st_size,
            "modified_time": stat.st_mtime,
            "created_time": stat.st_ctime,
            "is_directory": safe_path.is_dir(),
            "is_file": safe_path.is_file(),
            "is_symlink": safe_path.is_symlink()
        }
        return json.dumps(info, indent=2)

    async def _tool_hash_file(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for hash_file.")
        safe_path = self._resolve_safe_path(tool_input["path"])
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {tool_input['path']}")
        if not safe_path.is_file():
            raise ValueError(f"Path is not a file: {tool_input['path']}")
            
        algo_name = tool_input.get("algorithm", "sha256").lower()
        if algo_name not in ("md5", "sha256"):
            raise ValueError("Unsupported hashing algorithm. Choose 'md5' or 'sha256'.")
            
        import hashlib
        hasher = hashlib.md5() if algo_name == "md5" else hashlib.sha256()
        with open(safe_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
                
        return json.dumps({
            "path": tool_input["path"],
            "algorithm": algo_name,
            "hash": hasher.hexdigest()
        })

    # â”€â”€ API / HTTP REQUEST TOOL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _tool_http_request(self, tool_input: dict[str, Any]) -> str:
        """Execute an outbound HTTP request (ADMIN only)."""
        import httpx

        url = tool_input.get("url")
        if not url:
            raise ValueError("Parameter 'url' is required for http_request.")

        method = (tool_input.get("method", "GET")).upper()
        headers = tool_input.get("headers") or {}
        body = tool_input.get("body")
        timeout = min(tool_input.get("timeout", 30), 120)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

        # Truncate large response bodies
        body_text = response.text[:self.settings.MAX_OUTPUT_BYTES]
        return json.dumps({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body_text,
            "url": str(response.url),
            "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 2)
        }, indent=2)

    # â”€â”€ MEMORY & KNOWLEDGE TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _get_memory_store_path(self) -> Path:
        """Return the path to the JSON-backed memory store."""
        store_path = self.workspace_root / ".thinkbox" / "memory"
        store_path.mkdir(parents=True, exist_ok=True)
        return store_path

    def _load_memory_index(self) -> dict:
        """Load the memory index from disk."""
        index_path = self._get_memory_store_path() / "_index.json"
        if index_path.exists():
            return json.loads(index_path.read_text(encoding="utf-8"))
        return {}

    def _save_memory_index(self, index: dict) -> None:
        """Save the memory index to disk."""
        index_path = self._get_memory_store_path() / "_index.json"
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    async def _tool_memory_store(self, tool_input: dict[str, Any]) -> str:
        """Store a key-value entry in persistent memory."""
        key = tool_input.get("key")
        content = tool_input.get("content")
        tags = tool_input.get("tags", [])
        if not key or content is None:
            raise ValueError("Parameters 'key' and 'content' are required for memory_store.")

        store_path = self._get_memory_store_path()

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
        index = self._load_memory_index()
        index[key] = {"tags": tags or [], "file": f"{safe_key}.json"}
        self._save_memory_index(index)

        return json.dumps({"status": "stored", "key": key})

    async def _tool_memory_retrieve(self, tool_input: dict[str, Any]) -> str:
        """Retrieve a specific memory entry by key."""
        key = tool_input.get("key")
        if not key:
            raise ValueError("Parameter 'key' is required for memory_retrieve.")

        index = self._load_memory_index()
        if key not in index:
            raise FileNotFoundError(f"Memory key not found: {key}")

        store_path = self._get_memory_store_path()
        entry_path = store_path / index[key]["file"]
        if not entry_path.exists():
            raise FileNotFoundError(f"Memory file missing for key: {key}")

        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        return json.dumps(entry, indent=2)

    async def _tool_memory_search(self, tool_input: dict[str, Any]) -> str:
        """Search memory entries by query string and optional tags."""
        query = tool_input.get("query", "").lower()
        limit = tool_input.get("limit", 10)
        filter_tags = tool_input.get("tags", [])

        if not query:
            raise ValueError("Parameter 'query' is required for memory_search.")

        store_path = self._get_memory_store_path()
        index = self._load_memory_index()
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

    async def _tool_memory_delete(self, tool_input: dict[str, Any]) -> str:
        """Delete a memory entry by key (ADMIN only)."""
        key = tool_input.get("key")
        if not key:
            raise ValueError("Parameter 'key' is required for memory_delete.")

        index = self._load_memory_index()
        if key not in index:
            raise FileNotFoundError(f"Memory key not found: {key}")

        store_path = self._get_memory_store_path()
        entry_path = store_path / index[key]["file"]
        if entry_path.exists():
            entry_path.unlink()

        del index[key]
        self._save_memory_index(index)

        return json.dumps({"status": "deleted", "key": key})

    async def _tool_memory_list(self, tool_input: dict[str, Any]) -> str:
        """List all memory keys, optionally filtered by tags."""
        filter_tags = tool_input.get("tags", [])
        limit = tool_input.get("limit", 50)

        index = self._load_memory_index()
        keys = []

        for key, meta in index.items():
            if filter_tags:
                if not set(filter_tags).intersection(set(meta.get("tags", []))):
                    continue
            keys.append({"key": key, "tags": meta.get("tags", [])})
            if len(keys) >= limit:
                break

        return json.dumps({"count": len(keys), "keys": keys}, indent=2)

    # â”€â”€ SHELL / SYSTEM COMMAND TOOL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _tool_shell_exec(self, tool_input: dict[str, Any]) -> str:
        """Execute a shell command in the workspace (ADMIN only)."""
        import asyncio
        import sys

        command = tool_input.get("command")
        if not command:
            raise ValueError("Parameter 'command' is required for shell_exec.")

        timeout = min(tool_input.get("timeout", 30), 300)
        cwd = tool_input.get("cwd")

        if cwd:
            work_dir = self._resolve_safe_path(cwd)
        else:
            work_dir = self.workspace_root

        # Use shell=True on Windows, shell on Unix
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            timed_out = False
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            timed_out = True
            exit_code = -1

        return json.dumps({
            "stdout": stdout_bytes.decode("utf-8", errors="replace")[:self.settings.MAX_OUTPUT_BYTES],
            "stderr": stderr_bytes.decode("utf-8", errors="replace")[:self.settings.MAX_OUTPUT_BYTES],
            "exit_code": exit_code,
            "timed_out": timed_out,
        }, indent=2)

    # â”€â”€ COMMUNICATION TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _tool_send_email(self, tool_input: dict[str, Any]) -> str:
        """Send an email via SMTP (ADMIN only). Requires SMTP config in .env."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        to = tool_input.get("to")
        subject = tool_input.get("subject")
        body = tool_input.get("body")
        is_html = tool_input.get("html", False)

        if not to or not subject or not body:
            raise ValueError("Parameters 'to', 'subject', and 'body' are required for send_email.")

        s = self.settings
        if not s.SMTP_HOST or not s.SMTP_USER or not s.SMTP_PASSWORD:
            raise RuntimeError(
                "Email not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD in .env"
            )

        msg = MIMEMultipart("alternative")
        msg["From"] = s.SMTP_FROM or s.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject

        content_type = "html" if is_html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        try:
            with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=30) as server:
                if s.SMTP_USE_TLS:
                    server.starttls()
                server.login(s.SMTP_USER, s.SMTP_PASSWORD)
                server.send_message(msg)
                logger.info(f"ðŸ“§ Email sent to {to} (subject: {subject})")
        except Exception as e:
            raise RuntimeError(f"Failed to send email: {e}")

        return json.dumps({"status": "sent", "to": to, "subject": subject})

    async def _tool_send_telegram(self, tool_input: dict[str, Any]) -> str:
        """Send a Telegram message via Bot API (ADMIN only). Requires TELEGRAM_BOT_TOKEN in .env."""
        import httpx

        chat_id = tool_input.get("chat_id")
        message = tool_input.get("message")
        parse_mode = tool_input.get("parse_mode")

        if not chat_id or not message:
            raise ValueError("Parameters 'chat_id' and 'message' are required for send_telegram.")

        token = self.settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env"
            )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)

        resp_data = resp.json()
        if not resp_data.get("ok"):
            error_desc = resp_data.get("description", "Unknown Telegram API error")
            raise RuntimeError(f"Telegram API error: {error_desc}")

        logger.info(f"ðŸ“¨ Telegram message sent to {chat_id}")
        return json.dumps({
            "status": "sent",
            "chat_id": chat_id,
            "message_id": resp_data.get("result", {}).get("message_id")
        })

