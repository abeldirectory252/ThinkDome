"""ThinkDome — Secure LLM Sandbox Orchestrator & Application Framework.

Basic usage::

    from thinkdome import Sandbox

    with Sandbox() as dome:
        result = dome.run("print('Hello from ThinkDome!')")
        print(result.output)

Or as a FastAPI server::

    thinkdome serve --host 0.0.0.0 --port 8000

Framework API::

    import thinkdome

    @thinkdome.whitelist()
    def my_method(arg):
        return arg

    result = thinkdome.call("module.my_method", arg="value")
"""

from thinkdome._version import __version__
from thinkdome.sandbox import Sandbox, SandboxResult


def whitelist(methods=None, allow_guest=False, roles=None, require_privilege=True):
    """Mark a Python function as callable via the ThinkDome RPC interface.

    Every function is a privilege by default, but user/developer can customize
    it to not having it intentionally (e.g. require_privilege=False, allow_guest=True).
    """
    from thinkdome.core.handler import _whitelist_registry

    custom_name = methods if isinstance(methods, str) else None

    def decorator(fn):
        dotted = custom_name or f"{fn.__module__}.{fn.__qualname__}"
        entry = {
            "fn": fn,
            "dotted_path": dotted,
            "allow_guest": allow_guest,
            "require_privilege": require_privilege,
            "roles": set(r.upper() for r in (roles or [])),
            "methods": methods if not isinstance(methods, str) else None,
        }
        _whitelist_registry[dotted] = entry
        _whitelist_registry[fn.__qualname__] = entry
        _whitelist_registry[fn.__name__] = entry
        if custom_name:
            _whitelist_registry[custom_name] = entry
        fn._is_whitelisted = True
        fn._whitelist_meta = entry
        return fn

    if callable(methods):
        fn = methods
        methods = None
        return decorator(fn)

    return decorator


def call(method, **kwargs):
    """Execute a whitelisted method by its dotted path."""
    from thinkdome.core.handler import resolve_and_call
    return resolve_and_call(method, **kwargs)


def get_session():
    """Return the current session context, or None if not inside a request."""
    from thinkdome.core.handler import _get_current_session
    return _get_current_session()


def has_permission(doctype=None, perm_type="read", doc=None, user=None):
    """Check whether the current user has the specified dynamic document privilege."""
    session = get_session()
    if session is None:
        return True

    roles = set()
    user_id = user
    role = session.get("role")
    if role:
        roles.add(str(role).upper())
    for r in session.get("roles", []):
        roles.add(str(r).upper())
    if not user_id:
        user_id = session.get("username") or session.get("user_id")

    from thinkdome.security.rbac.protocol import dynamic_role_protocol
    return dynamic_role_protocol.has_document_permission(
        roles=roles,
        document_type=doctype or "Document",
        action=perm_type,
        doc_name=doc,
        user_id=user_id,
    )


def only_for(*roles):
    """Raise PermissionError if current user does not hold one of the named roles."""
    session = get_session()
    if session is None:
        return
    user_role = str(session.get("role", "")).upper()
    roles_set = {user_role}
    for r in session.get("roles", []):
        roles_set.add(str(r).upper())
    normalized = set(r.upper() for r in roles)
    from thinkdome.security.identity.core import is_admin_role
    if any(is_admin_role(r) for r in roles_set):
        return
    from thinkdome.security.rbac.protocol import dynamic_role_protocol
    expanded = dynamic_role_protocol.get_inherited_roles(roles_set)
    if not expanded.intersection(normalized):
        raise PermissionError(f"This operation requires one of {roles}, you have '{user_role}'")


def __getattr__(name):
    if name == "ui":
        from thinkdome.core import ui
        return ui
    raise AttributeError(f"module 'thinkdome' has no attribute {name!r}")


__all__ = [
    "Sandbox",
    "SandboxResult",
    "__version__",
    "whitelist",
    "call",
    "get_session",
    "has_permission",
    "only_for",
]
