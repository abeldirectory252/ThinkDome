import os
import json
import re
import hashlib
from pathlib import Path
from typing import Any
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.path_utils import resolve_safe_path
from thinkdome.platform.orchestration.search.models import SearchRequest
from thinkdome.platform.orchestration.orchestrator_models import (
    WebSearchInput, GrepSearchInput, FindFilesInput, GetFileInfoInput, HashFileInput
)

@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for queries"
    required_scope = "web:search"
    input_schema = WebSearchInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "query" not in tool_input:
            raise ValueError("Parameter 'query' is required for web_search.")
        
        max_results = tool_input.get("max_results", 10)
        request = SearchRequest(query=tool_input["query"], max_results=max_results)
        ctx = get_context()
        
        resp = await ctx.search_service.search(request)
        
        results_list = []
        for r in resp.results:
            results_list.append(f"Title: {r.title}\nURL: {r.url}\nSnippet: {r.snippet}\n---")
            
        return "\n\n".join(results_list) if results_list else "No results found."


@register_tool
class GrepSearchTool(BaseTool):
    name = "grep_search"
    description = "Perform regex grep search over files in the workspace"
    required_scope = "file:read"
    input_schema = GrepSearchInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "pattern" not in tool_input:
            raise ValueError("Parameter 'pattern' is required for grep_search.")
        
        path_str = tool_input.get("path", ".")
        ctx = get_context()
        safe_path = resolve_safe_path(path_str, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"Search path not found: {path_str}")
            
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
                        rel_path = fpath.relative_to(ctx.workspace_dir)
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


@register_tool
class FindFilesTool(BaseTool):
    name = "find_files"
    description = "Find files matching glob pattern under a directory"
    required_scope = "file:read"
    input_schema = FindFilesInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "pattern" not in tool_input:
            raise ValueError("Parameter 'pattern' is required for find_files.")
        
        path_str = tool_input.get("path", ".")
        ctx = get_context()
        safe_path = resolve_safe_path(path_str, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"Search path not found: {path_str}")
            
        pattern = tool_input["pattern"]
        matched_files = []
        
        search_root = safe_path if safe_path.is_dir() else safe_path.parent
        for item in search_root.rglob(pattern):
            if item.is_file():
                rel_path = item.relative_to(ctx.workspace_dir)
                matched_files.append(str(rel_path))
                if len(matched_files) >= 500:
                    break
        return json.dumps(matched_files, indent=2)


@register_tool
class GetFileInfoTool(BaseTool):
    name = "get_file_info"
    description = "Get directory or file metadata (size, modified time, etc.)"
    required_scope = "file:read"
    input_schema = GetFileInfoInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for get_file_info.")
        ctx = get_context()
        safe_path = resolve_safe_path(tool_input["path"], ctx.workspace_dir)
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


@register_tool
class HashFileTool(BaseTool):
    name = "hash_file"
    description = "Compute the MD5 or SHA256 checksum of a file"
    required_scope = "file:read"
    input_schema = HashFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "path" not in tool_input:
            raise ValueError("Parameter 'path' is required for hash_file.")
        ctx = get_context()
        safe_path = resolve_safe_path(tool_input["path"], ctx.workspace_dir)
            
        algo_name = tool_input.get("algorithm", "sha256").lower()
        if algo_name not in ("md5", "sha256"):
            raise ValueError("Unsupported hashing algorithm. Choose 'md5' or 'sha256'.")
            
        hasher = hashlib.md5() if algo_name == "md5" else hashlib.sha256()
        if safe_path.exists():
            if not safe_path.is_file():
                raise ValueError(f"Path is not a file: {tool_input['path']}")
            with open(safe_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
        else:
            # File writes are tenant-scoped FileBox entries; read tools must
            # resolve the same namespace instead of silently switching to the
            # host workspace and reporting a false "not found".
            from thinkdome.platform.storage.filebox.service import FileBoxService, DEFAULT_FOLDERS
            logical = str(tool_input["path"]).strip().strip("/")
            folder, filename = (logical.split("/", 1) if "/" in logical else ("workspace", logical))
            if folder not in DEFAULT_FOLDERS or not filename:
                raise FileNotFoundError(f"File not found: {tool_input['path']}")
            identity = getattr(ctx, "identity", None)
            metadata = getattr(identity, "metadata", {}) or {}
            owner = str(metadata.get("workspace_id") or ctx.username).strip().lower()
            tenant = getattr(identity, "tenant_id", None) or "default"
            meta = next((m for m in FileBoxService().list(tenant_id=tenant, owner_id=owner)
                         if m.folder == folder and m.filename == filename), None)
            content = FileBoxService().read(meta.id, tenant_id=tenant, owner_id=owner)[0] if meta else None
            if content is None:
                raise FileNotFoundError(f"File not found: {tool_input['path']}")
            hasher.update(content)
                
        return json.dumps({
            "path": tool_input["path"],
            "algorithm": algo_name,
            "hash": hasher.hexdigest()
        })
