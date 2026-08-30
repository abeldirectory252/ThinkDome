"""Authorization primitives for the Dynamic UI framework.

UI visibility is a server-side policy decision.  The client may render the
payload it receives, but it must never be responsible for deciding whether a
workspace, page, or menu item is present in that payload.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Set


ROLE_FIELD = "allowed_roles"
# UI administration is a platform capability; platform administrators must
# retain visibility even when an application page's audience is narrower.
PRIVILEGED_ROLES = {"SUPER_ADMIN", "SUPERADMIN", "ENTERPRISE_ADMIN", "ADMIN", "ADMINISTRATOR"}


def normalize_roles(roles: Optional[Iterable[Any]]) -> Set[str]:
    """Return canonical role names, ignoring empty and malformed values."""
    if not roles:
        return set()
    return {str(role).strip().upper() for role in roles if str(role).strip()}


def required_roles(resource: Mapping[str, Any]) -> Set[str]:
    """Read the canonical role field, with compatibility for old configs."""
    configured = resource.get(ROLE_FIELD)
    if configured is None:
        configured = resource.get("roles")
    if isinstance(configured, str):
        configured = [configured]
    return normalize_roles(configured if isinstance(configured, (list, tuple, set)) else None)


def can_view(resource: Mapping[str, Any], user_roles: Optional[Iterable[Any]]) -> bool:
    """Evaluate an allow-list policy.

    ``None`` means the caller did not provide an identity (developer/internal
    reads).  An empty set is an identified user with no roles and therefore
    cannot access a role-protected resource.
    """
    required = required_roles(resource)
    if not required:
        return True
    if user_roles is None:
        return False
    roles = normalize_roles(user_roles)
    if roles.intersection(PRIVILEGED_ROLES):
        return True
    return bool(required.intersection(roles))
