"""Path resolution utilities for safe workspace boundary checks."""

import os
from pathlib import Path


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
