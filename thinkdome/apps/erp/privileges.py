"""ERP Privilege Enforcement System.

Controls access to CRUD operations on ERP data.
READ is always allowed by default.
CREATE, UPDATE, DELETE require elevated privileges defined in config.json.
"""

from __future__ import annotations

import json
import logging
import functools
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.json"
_privilege_cache: Optional[Dict[str, List[str]]] = None


def _load_privilege_config() -> Dict[str, List[str]]:
    """Load privilege levels from config.json, with caching."""
    global _privilege_cache
    if _privilege_cache is not None:
        return _privilege_cache

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        _privilege_cache = config.get("privilege_levels", {
            "read": ["*"],
            "create": ["erp_admin", "ADMIN"],
            "update": ["erp_admin", "ADMIN"],
            "delete": ["ADMIN"],
        })
    except Exception as e:
        logger.warning(f"Failed to load ERP privilege config: {e}. Using defaults.")
        _privilege_cache = {
            "read": ["*"],
            "create": ["erp_admin", "ADMIN"],
            "update": ["erp_admin", "ADMIN"],
            "delete": ["ADMIN"],
        }
    return _privilege_cache


def reload_privileges() -> None:
    """Force reload of privilege configuration."""
    global _privilege_cache
    _privilege_cache = None
    _load_privilege_config()


class PrivilegeError(PermissionError):
    """Raised when a caller lacks the required privilege for an operation."""

    def __init__(self, operation: str, caller_role: str):
        self.operation = operation
        self.caller_role = caller_role
        super().__init__(
            f"Privilege denied: operation '{operation}' requires elevated access. "
            f"Your role '{caller_role}' is not in the allowed list. "
            f"Contact an administrator to request '{operation}' privilege."
        )


def check_privilege(caller_role: str, operation: str) -> bool:
    """Check if a caller role has the required privilege for an operation.

    Args:
        caller_role: The role of the calling user/agent (from tool context).
        operation: One of 'read', 'create', 'update', 'delete'.

    Returns:
        True if allowed.

    Raises:
        PrivilegeError: If the caller lacks privilege.
    """
    privileges = _load_privilege_config()
    allowed_roles = privileges.get(operation, [])

    # Wildcard — everyone is allowed
    if "*" in allowed_roles:
        return True

    # Check case-insensitive role match
    caller_upper = caller_role.upper()
    for role in allowed_roles:
        if role.upper() == caller_upper:
            return True

    raise PrivilegeError(operation, caller_role)


def require_privilege(operation: str) -> Callable:
    """Decorator that enforces privilege checks before tool execution.

    Usage:
        @require_privilege("create")
        async def my_write_tool(self, tool_input):
            ...

    The decorated function must receive a tool_input dict.
    The caller_role is extracted from the active ToolContext.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, tool_input: dict, *args, **kwargs) -> Any:
            from thinkdome.orchestration.tools import get_context
            try:
                ctx = get_context()
                caller_role = ctx.caller_role
            except RuntimeError:
                # If no context available, default to most restrictive
                caller_role = "anonymous"

            check_privilege(caller_role, operation)
            return await func(self, tool_input, *args, **kwargs)
        return wrapper
    return decorator


def get_privilege_summary() -> Dict[str, Any]:
    """Return a human-readable summary of the privilege configuration."""
    privileges = _load_privilege_config()
    return {
        "read": {
            "allowed_roles": privileges.get("read", []),
            "description": "View/query data — default for all users",
        },
        "create": {
            "allowed_roles": privileges.get("create", []),
            "description": "Create new records (invoices, entries, etc.)",
        },
        "update": {
            "allowed_roles": privileges.get("update", []),
            "description": "Modify existing records",
        },
        "delete": {
            "allowed_roles": privileges.get("delete", []),
            "description": "Permanently remove records",
        },
    }
