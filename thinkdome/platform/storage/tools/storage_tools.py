import os
import json
from pathlib import Path
from typing import Any
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.path_utils import resolve_safe_path
from thinkdome.platform.storage.workspace_crypto import workspace_cipher
from thinkdome.platform.orchestration.orchestrator_models import (
    ReadFileInput, WriteFileInput, ListDirInput, FileExistsInput, MakeDirInput,
    RemoveFileInput, RemoveDirInput, MoveFileInput, CopyFileInput
)


def _owner(ctx) -> str:
    identity = getattr(ctx, "identity", None)
    metadata = getattr(identity, "metadata", {}) or {}
    return str(metadata.get("workspace_id") or ctx.username).strip().lower()


@register_tool
class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file's content from the workspace"
    required_scope = "file:read"
    input_schema = ReadFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        if not path:
            raise ValueError("Parameter 'path' is required for read_file.")
        ctx = get_context()
        from thinkdome.platform.storage.filebox.service import FileBoxService, DEFAULT_FOLDERS
        logical = str(path).strip().strip("/")
        parts = logical.split("/", 1)
        folder, filename = (parts[0], parts[1]) if len(parts) == 2 else ("workspace", parts[0])
        if folder not in DEFAULT_FOLDERS or not filename:
            raise FileNotFoundError(f"File not found in FileBox: {path}")
        service = FileBoxService()
        tenant = getattr(getattr(ctx, "identity", None), "tenant_id", None) or "default"
        owner = _owner(ctx)
        meta = next((m for m in service.list(tenant_id=tenant, owner_id=owner)
                     if m.folder == folder and m.filename == filename), None)
        if not meta:
            raise FileNotFoundError(f"File not found in FileBox: {path}")
        result = service.read(meta.id, tenant_id=tenant, owner_id=owner)
        if result is None:
            raise FileNotFoundError(f"File not found in FileBox: {path}")
        return result[0].decode("utf-8")


@register_tool
class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file in the workspace"
    required_scope = "file:write"
    input_schema = WriteFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        content = tool_input.get("content")
        if not path or content is None:
            raise ValueError("Parameters 'path' and 'content' are required for write_file.")
        ctx = get_context()
        from thinkdome.platform.storage.filebox.service import FileBoxService
        logical = str(path).strip().strip("/")
        parts = logical.split("/", 1)
        folder, filename = (parts[0], parts[1]) if len(parts) == 2 else ("workspace", parts[0])
        tenant = getattr(getattr(ctx, "identity", None), "tenant_id", None) or "default"
        service = FileBoxService()
        owner = _owner(ctx)
        available = list(service.ensure_layout(tenant_id=tenant, owner_id=owner).keys())
        if folder not in available or not filename:
            folders = ", ".join(f"/{name}" for name in available)
            raise ValueError(f"Invalid FileBox path. Available folders: {folders}. Use '/<folder>/<filename>'.")
        service.create(tenant_id=tenant, owner_id=owner, filename=filename,
                                content=content.encode("utf-8"), permanent=True,
                                folder=folder, override=True, conflict="override")
        return json.dumps({"status": "success", "bytes_written": len(content)})


@register_tool
class ListDirTool(BaseTool):
    name = "list_dir"
    description = "List contents of a directory in the workspace"
    required_scope = "file:read"
    input_schema = ListDirInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path", ".")
        ctx = get_context()
        # FileBox is the caller's only visible disk. Never enumerate the
        # legacy host workspace, regardless of the supplied path.
        from thinkdome.platform.storage.filebox.service import FileBoxService, DEFAULT_FOLDERS
        tenant = getattr(getattr(ctx, "identity", None), "tenant_id", None) or "default"
        service = FileBoxService()
        owner = _owner(ctx)
        folders = service.ensure_layout(tenant_id=tenant, owner_id=owner)
        logical = str(path).strip().strip("/")
        if logical in {"", "."}:
            entries = [{"name": name, "path": name, "type": "dir", "size_bytes": 0} for name in folders]
        else:
            folder = logical.split("/", 1)[0]
            if folder not in DEFAULT_FOLDERS:
                raise FileNotFoundError(f"Directory not found in FileBox: {path}")
            entries = []
        for item in service.list(tenant_id=tenant, owner_id=owner):
            if logical in {"", "."} or logical == item.folder:
                entries.append({"name": item.filename, "path": f"{item.folder}/{item.filename}", "type": "file", "size_bytes": item.size_bytes})
        return json.dumps(entries, indent=2)
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        user_workspace = ctx.workspace_dir
        cipher = workspace_cipher(_owner(ctx))
        entries = []
        for entry in sorted(safe_path.iterdir()):
            try:
                rel_path = entry.relative_to(user_workspace)
            except ValueError:
                rel_path = entry.name
            is_directory = entry.is_dir()
            if is_directory:
                # Directory names are metadata; file contents remain encrypted.
                size = 0
            else:
                # Accessing a listing authenticates the tenant and migrates
                # legacy plaintext files to encrypted-at-rest storage.
                cipher.read(entry)
            size = entry.stat().st_size if not is_directory else 0
            entries.append({
                "name": entry.name,
                "path": str(rel_path),
                "type": "dir" if is_directory else "file",
                "size_bytes": size
            })
        return json.dumps(entries, indent=2)


@register_tool
class FileExistsTool(BaseTool):
    name = "file_exists"
    description = "Check if a file or directory exists in the workspace"
    required_scope = "file:read"
    input_schema = FileExistsInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        if not path:
            raise ValueError("Parameter 'path' is required for file_exists.")
        ctx = get_context()
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        return json.dumps({
            "path": path,
            "exists": safe_path.exists(),
            "is_file": safe_path.is_file() if safe_path.exists() else False,
            "is_dir": safe_path.is_dir() if safe_path.exists() else False
        })


@register_tool
class MakeDirTool(BaseTool):
    name = "make_dir"
    description = "Create a directory in the workspace"
    required_scope = "file:write"
    input_schema = MakeDirInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        if not path:
            raise ValueError("Parameter 'path' is required for make_dir.")
        ctx = get_context()
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        safe_path.mkdir(parents=True, exist_ok=True)
        return json.dumps({"status": "success", "path": path})


@register_tool
class RemoveFileTool(BaseTool):
    name = "remove_file"
    description = "Remove/delete a file from the workspace"
    required_scope = "file:destructive"
    input_schema = RemoveFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        if not path:
            raise ValueError("Parameter 'path' is required for remove_file.")
        ctx = get_context()
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not safe_path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        safe_path.unlink()
        return json.dumps({"status": "success", "removed": path})


@register_tool
class RemoveDirTool(BaseTool):
    name = "remove_dir"
    description = "Remove/delete a directory recursively"
    required_scope = "file:destructive"
    input_schema = RemoveDirInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        path = tool_input.get("path")
        recursive = tool_input.get("recursive", False)
        if not path:
            raise ValueError("Parameter 'path' is required for remove_dir.")
        ctx = get_context()
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        if recursive:
            import shutil
            shutil.rmtree(safe_path)
        else:
            try:
                safe_path.rmdir()
            except OSError as e:
                raise ValueError(f"Failed to remove directory (may not be empty): {e}")
        return json.dumps({"status": "success", "removed": path})


@register_tool
class MoveFileTool(BaseTool):
    name = "move_file"
    description = "Move/rename a file or directory"
    required_scope = "file:destructive"
    input_schema = MoveFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        src = tool_input.get("source")
        dst = tool_input.get("destination")
        if not src or not dst:
            raise ValueError("Parameters 'source' and 'destination' are required for move_file.")
        ctx = get_context()
        safe_src = resolve_safe_path(src, ctx.workspace_dir)
        safe_dst = resolve_safe_path(dst, ctx.workspace_dir)
        
        if not safe_src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        safe_dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(safe_src), str(safe_dst))
        return json.dumps({"status": "success", "source": src, "destination": dst})


@register_tool
class CopyFileTool(BaseTool):
    name = "copy_file"
    description = "Copy a file from source to destination"
    required_scope = "file:write"
    input_schema = CopyFileInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        src = tool_input.get("source")
        dst = tool_input.get("destination")
        if not src or not dst:
            raise ValueError("Parameters 'source' and 'destination' are required for copy_file.")
        ctx = get_context()
        safe_src = resolve_safe_path(src, ctx.workspace_dir)
        safe_dst = resolve_safe_path(dst, ctx.workspace_dir)
        
        if not safe_src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")
        if not safe_src.is_file():
            raise ValueError("Source must be a file, not a directory.")
        safe_dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(str(safe_src), str(safe_dst))
        return json.dumps({"status": "success", "source": src, "destination": dst})
