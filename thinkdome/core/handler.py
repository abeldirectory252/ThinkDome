"""ThinkDome Method Handler — Frappe-style RPC resolution engine.

This module owns the global method registry, session context threading,
permission enforcement, and dotted-path resolution for thinkdome.call().

Architecture::

    thinkdome.call("thinkdome.core.ui.api.get_navigation")
           │
           ▼
    handler.resolve_and_call(method, **kwargs)
           │
           ├── 1. Check _whitelist_registry
           ├── 2. Fallback: importlib resolve dotted path
           ├── 3. Enforce @whitelist() presence
           ├── 4. Enforce role-based permissions
           └── 5. Execute fn(**kwargs) and return result
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)

# ── Global Whitelist Registry ─────────────────────────────────────────────────
# Maps dotted_path → { fn, allow_guest, roles, ... }
_whitelist_registry: Dict[str, Dict[str, Any]] = {}

# ── Thread-Local Session Context ──────────────────────────────────────────────
_local = threading.local()


def _get_current_session() -> Optional[Dict[str, Any]]:
    """Return the session dict attached to the current thread, or None."""
    return getattr(_local, "session", None)


def _set_current_session(session: Optional[Dict[str, Any]]) -> None:
    """Attach a session context to the current thread."""
    _local.session = session


class SessionContext:
    """Context manager that binds a user session to the current thread.

    Usage::

        with SessionContext(user_dict):
            thinkdome.call("some.method")
    """

    def __init__(self, session: Dict[str, Any]) -> None:
        self._session = session
        self._previous: Optional[Dict[str, Any]] = None

    def __enter__(self) -> Dict[str, Any]:
        self._previous = _get_current_session()
        _set_current_session(self._session)
        return self._session

    def __exit__(self, *exc_info) -> None:
        _set_current_session(self._previous)


# ── Dotted Path Resolver ──────────────────────────────────────────────────────

def _resolve_method(dotted_path: str) -> Callable:
    """Resolve a dotted Python path to a callable function.

    Tries the whitelist registry first, then falls back to importlib
    resolution (module.submodule.function).
    """
    # 1. Direct registry hit
    if dotted_path in _whitelist_registry:
        return _whitelist_registry[dotted_path]["fn"]

    # 2. importlib resolution
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise AttributeError(f"Cannot resolve method path: {dotted_path!r}")

    module_path, func_name = parts
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        # Try progressively shorter module paths for nested attrs
        segments = dotted_path.split(".")
        obj = None
        for i in range(len(segments) - 1, 0, -1):
            mod_candidate = ".".join(segments[:i])
            try:
                obj = importlib.import_module(mod_candidate)
                for attr_name in segments[i:]:
                    obj = getattr(obj, attr_name)
                break
            except (ModuleNotFoundError, AttributeError):
                continue
        if obj is None or not callable(obj):
            raise AttributeError(
                f"Method {dotted_path!r} could not be resolved. "
                f"Ensure the module exists and the function is decorated with @thinkdome.whitelist()"
            )
        return obj

    fn = getattr(module, func_name, None)
    if fn is None:
        raise AttributeError(
            f"Module {module_path!r} has no attribute {func_name!r}"
        )
    if not callable(fn):
        raise TypeError(f"{dotted_path!r} resolved to a non-callable: {type(fn)}")
    return fn


# ── Permission Enforcement ────────────────────────────────────────────────────

def _enforce_permissions(fn: Callable, session: Optional[Dict[str, Any]]) -> None:
    """Raise PermissionError if the session context lacks required authorization."""
    meta = getattr(fn, "_whitelist_meta", None)
    if meta is None:
        # Function was resolved but is not whitelisted
        raise PermissionError(
            f"Method {fn.__module__}.{fn.__qualname__} is not whitelisted. "
            f"Decorate it with @thinkdome.whitelist() to allow RPC access."
        )

    allow_guest = meta.get("allow_guest", False)
    required_roles: Set[str] = meta.get("roles", set())

    if not session:
        # No session context: programmatic call from scripts/CLI/tests
        return

    user_role = str(session.get("role", "")).upper()

    if not allow_guest and user_role in ("GUEST", ""):
        raise PermissionError("Guest access is not permitted for this method")

    if required_roles and user_role not in required_roles:
        from thinkdome.security.identity.core import is_admin_role
        if not is_admin_role(user_role):
            raise PermissionError(
                f"Insufficient permissions. Required: {required_roles}, current role: {user_role}"
            )


# ── Primary Call Interface ────────────────────────────────────────────────────

def resolve_and_call(method: str, **kwargs) -> Any:
    """Resolve a dotted method path, enforce permissions, execute, and return.

    This is the backend implementation of ``thinkdome.call()``.
    """
    fn = _resolve_method(method)
    session = _get_current_session()
    _enforce_permissions(fn, session)

    # Inject session into functions that accept it
    sig = inspect.signature(fn)
    if "session" in sig.parameters and "session" not in kwargs:
        kwargs["session"] = session

    try:
        result = fn(**kwargs)
        return result
    except Exception:
        logger.exception(f"Error executing method {method!r}")
        raise


def get_all_whitelisted_methods() -> Dict[str, Dict[str, Any]]:
    """Return metadata for all registered whitelisted methods.

    Useful for introspection, docs generation, and the /api/method endpoint.
    """
    methods = {}
    for dotted_path, entry in _whitelist_registry.items():
        # Skip short-name aliases to avoid duplicates
        if "." not in dotted_path:
            continue
        fn = entry["fn"]
        sig = inspect.signature(fn)
        methods[dotted_path] = {
            "module": fn.__module__,
            "name": fn.__qualname__,
            "allow_guest": entry.get("allow_guest", False),
            "roles": list(entry.get("roles", [])),
            "parameters": [
                {
                    "name": p.name,
                    "default": None if p.default is inspect.Parameter.empty else repr(p.default),
                    "required": p.default is inspect.Parameter.empty and p.name != "session",
                }
                for p in sig.parameters.values()
            ],
            "docstring": (fn.__doc__ or "").strip(),
        }
    return methods
