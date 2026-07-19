import os
import json
from pathlib import Path
from typing import Any
from thinkdome.core.tools import BaseTool, register_tool, get_context
from thinkdome.modules.orchestrator.orchestrator_models import (
    ReadFileInput, WriteFileInput, ListDirInput, FileExistsInput, MakeDirInput,
    RemoveFileInput, RemoveDirInput, MoveFileInput, CopyFileInput
)

def resolve_safe_path(path_str: str, workspace_root: Path) -> Path:
    """Resolve path and ensure it remains within the workspace directory."""
    cleaned = path_str.lstrip("/\\")
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].lstrip("/\\")
    
    target_path = Path(os.path.abspath(workspace_root / cleaned)).resolve()
    resolved_root = workspace_root.resolve()
    try:
        target_path.relative_to(resolved_root)
    except ValueError:
        raise PermissionError(f"Access denied: path '{path_str}' escapes workspace boundaries.")
    return target_path


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
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not safe_path.is_file():
            raise ValueError(f"Path is a directory, not a file: {path}")
        try:
            return safe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            import base64
            binary_content = safe_path.read_bytes()
            return base64.b64encode(binary_content).decode("utf-8")


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
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding="utf-8")
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
        safe_path = resolve_safe_path(path, ctx.workspace_dir)
        if not safe_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        user_workspace = ctx.workspace_dir
        entries = []
        for entry in sorted(safe_path.iterdir()):
            try:
                rel_path = entry.relative_to(user_workspace)
            except ValueError:
                rel_path = entry.name
            is_directory = entry.is_dir()
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
