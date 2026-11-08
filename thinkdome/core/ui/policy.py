"""Authorization primitives for the Dynamic UI framework.

UI visibility is a server-side policy decision.  The client may render the
payload it receives, but it must never be responsible for deciding whether a
workspace, page, or menu item is present in that payload.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Set


ROLE_FIELD = "allowed_roles"


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


def can_view(resource: Mapping[str, Any], user_roles: Optional[Iterable[Any]], user_id: Optional[str] = None) -> bool:
    """Evaluate dynamic role allocation policy for UI resources.

    ``None`` means the caller did not provide an identity (developer/internal
    reads). Evaluates dynamic privilege rules, privilege granters, and privilege
    denials via the centralized protocol.
    """
    if user_roles is None:
        return True

    roles = normalize_roles(user_roles)

    from thinkdome.security.rbac.protocol import dynamic_role_protocol

    # Dynamically resolve document type via pluggable DocumentTypeResolver
    doc_type = dynamic_role_protocol.resolve_document_type(resource)
    doc_name = resource.get("name") or resource.get("id") or resource.get("title")

    # 1. Check for intentional user customization (exemption)
    if dynamic_role_protocol.is_exempt(doc_type) or (doc_name and dynamic_role_protocol.is_exempt(doc_name)):
        return True

    # 2. Check for explicit denial via dynamic protocol (strict precedence)
    if user_id or roles:
        rules = dynamic_role_protocol._get_rules_for_evaluation(doc_type, level=0, doc_name=doc_name)
        for r in rules:
            if r.get("is_denial"):
                if user_id and r.get("user_id") == user_id:
                    return False
                if r.get("role") in roles:
                    return False

    # 2. Compatibility check for explicitly declared allowed_roles on the resource
    required = required_roles(resource)
    if not required:
        return True

    if not roles:
        return False

    from thinkdome.security.identity.core import is_admin_role
    if any(is_admin_role(r) for r in roles):
        return True

    expanded = dynamic_role_protocol.get_inherited_roles(roles)
    return bool(required.intersection(expanded))
