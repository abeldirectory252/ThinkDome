"""Security utilities: API key validation, rate limiting hooks."""

import logging
from typing import Optional

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from thinkdome.core.config import get_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """Verify API key if configured. Returns key or None if auth disabled."""
    settings = get_settings()
    if settings.API_KEY is None:
        return None  # Auth disabled
    if api_key is None or api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


# Search rate limiting and sanitization helpers
import time
from collections import defaultdict

class SimpleRateLimiter:
    """In-memory rate limiter for search tool API keys."""
    
    def __init__(self, limit: int = 30, window: float = 60.0):
        self.limit = limit
        self.window = window
        self.history = defaultdict(list)
        
    def check(self, name: str) -> bool:
        now = time.time()
        self.history[name] = [t for t in self.history[name] if now - t < self.window]
        if len(self.history[name]) >= self.limit:
            return False
        self.history[name].append(now)
        return True

_search_rate_limiter = SimpleRateLimiter(limit=30, window=60.0)

def get_search_rate_limiter() -> SimpleRateLimiter:
    return _search_rate_limiter

def sanitize_search_query(query: str) -> str:
    """Sanitize search query to prevent injection and strip formatting."""
    return query.strip()


# ── Enterprise RBAC & Institutional Security Engine ───────────────────────────

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Any, Optional, Union

class Role(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ENTERPRISE_ADMIN = "ENTERPRISE_ADMIN"
    ADMIN = "ADMIN"
    ORCH = "ORCH"
    IDE = "IDE"
    FINANCE_MANAGER = "FINANCE_MANAGER"
    FINANCE_USER = "FINANCE_USER"
    AUDITOR = "AUDITOR"
    SALES_USER = "SALES_USER"
    AGENT_STANDARD = "AGENT_STANDARD"
    LLM = "LLM"
    WEB = "WEB"
    ANONYMOUS = "ANONYMOUS"
    GUEST = "GUEST"

# Compatibility string constants
ROLE_ADMIN = Role.ADMIN.value
ROLE_LLM = Role.LLM.value
ROLE_ORCH = Role.ORCH.value
ROLE_IDE = Role.IDE.value
ROLE_WEB = Role.WEB.value

def is_admin_role(role: Optional[str]) -> bool:
    """Return whether a persisted role grants administrative access dynamically via RBAC."""
    if not role:
        return False
    normalized = str(role).strip().upper()
    try:
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        default_admin = dynamic_role_protocol.get_default_admin_role().upper()
        if normalized == default_admin or normalized.endswith("_ADMIN") or "ADMIN" in normalized:
            return True
        if dynamic_role_protocol.has_document_permission("Workspace", normalized, "write"):
            return True
        parent = dynamic_role_protocol._get_parent_role(normalized)
        if parent and is_admin_role(parent):
            return True
    except Exception:
        pass
    try:
        from thinkdome.security.rbac.models import Role as RoleModel
        r = RoleModel.query().filter(name=normalized).first()
        if r:
            if getattr(r, "is_admin", False):
                return True
            parent_id = getattr(r, "parent_role_id", None)
            if parent_id:
                parent_r = RoleModel.get(parent_id)
                if parent_r and is_admin_role(parent_r.name):
                    return True
    except Exception:
        pass
    return False
# No non-admin identity is globally trusted.  Sandboxes must be owned by the
# authenticated username/key or accessed through an explicit admin role.
GLOBAL_SANDBOX_OWNERS: set[str] = set()

# A user may have several assigned roles.  Never rely on database insertion
# order when choosing the role carried into tool authorization: a default
# AGENT_STANDARD role must not override SUPER_ADMIN/ADMIN privileges.
ROLE_PRIORITY = (
    Role.SUPER_ADMIN.value,
    Role.ENTERPRISE_ADMIN.value,
    Role.ADMIN.value,
    Role.ORCH.value,
    Role.IDE.value,
    Role.FINANCE_MANAGER.value,
    Role.AUDITOR.value,
    Role.WEB.value,
    Role.SDK.value if hasattr(Role, "SDK") else "SDK",
    Role.AGENT_STANDARD.value,
    Role.LLM.value,
    Role.GUEST.value,
)


def select_effective_role(
    roles,
    default: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    """Return the highest-privilege role deterministically.

    Authorization is derived exclusively from persisted role assignments.
    """
    if default is None:
        try:
            from thinkdome.security.rbac.protocol import dynamic_role_protocol
            default = dynamic_role_protocol.get_default_role()
        except Exception:
            default = Role.AGENT_STANDARD.value

    names = {str(role.name if hasattr(role, "name") else role).upper() for role in (roles or [])}
    if not names:
        return default

    # 1. Any administrator role takes top precedence dynamically
    for role_name in names:
        if is_admin_role(role_name):
            return role_name

    # 2. Check prioritized known roles (excluding low-level guest/anonymous)
    for role_name in ROLE_PRIORITY:
        if role_name in ("GUEST", "ANONYMOUS"):
            continue
        if role_name in names:
            return role_name

    # 3. Any non-guest custom role dynamically configured in database
    non_guest = [r for r in names if r not in ("GUEST", "ANONYMOUS")]
    if non_guest:
        return non_guest[0]

    if "GUEST" in names:
        return "GUEST"
    return next(iter(names), default)

@dataclass
class UserIdentity:
    """Enterprise Identity representing an authenticated user, agent, or service account."""
    username: str
    tenant_id: str = "default"
    roles: Set[str] = field(default_factory=set)
    permissions: Set[str] = field(default_factory=set)
    token_type: Optional[str] = None
    key_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserIdentity":
        """Construct UserIdentity from incoming request or dict representation."""
        if not isinstance(data, dict):
            return cls(username="anonymous", roles={"ANONYMOUS"})

        username = data.get("username") or data.get("sub") or "anonymous"
        tenant_id = data.get("tenant_id") or data.get("site_name") or "default"
        token_type = data.get("token_type")

        # Collect roles
        roles: Set[str] = set()
        raw_role = data.get("role") or data.get("caller_role")
        if raw_role:
            roles.add(str(raw_role).upper())
        if token_type:
            roles.add(str(token_type).upper())

        # If data includes role_profile or role_profile_name, resolve collection of role names
        role_profile_name = data.get("role_profile") or data.get("role_profile_name")
        if role_profile_name:
            try:
                from thinkdome.security.rbac.registry import rbac_registry
                prof = rbac_registry.get_role_profile(role_profile_name)
                if prof:
                    for r in prof.get("role_names", []):
                        roles.add(str(r).upper())
            except Exception:
                pass

        # If user has no roles or only generic role, attempt dynamic resolution for known user
        if username and username != "anonymous" and (not roles or roles == {"ANONYMOUS"} or roles == {"AGENT_STANDARD"}):
            try:
                from thinkdome.security.rbac.registry import rbac_registry
                user_dyn_roles = rbac_registry.get_user_roles(username)
                if user_dyn_roles:
                    roles.update(user_dyn_roles)
            except Exception:
                pass

        if not roles:
            roles.add(Role.ANONYMOUS.value)

        # Collect permissions
        raw_perms = data.get("permissions") or []
        permissions = set(raw_perms) if isinstance(raw_perms, (list, set, tuple)) else set()

        metadata = dict(data.get("metadata", {}) or {})
        if data.get("workspace_id"):
            metadata["workspace_id"] = data["workspace_id"]

        return cls(
            username=username,
            tenant_id=tenant_id,
            roles=roles,
            permissions=permissions,
            token_type=token_type,
            key_id=data.get("key_id"),
            metadata=metadata,
        )

    def is_admin(self) -> bool:
        """Check if identity possesses administrator level authority."""
        if any(is_admin_role(r) for r in self.roles):
            return True
        if "*:*:*" in self.permissions or "*" in self.permissions or "system:admin:manage" in self.permissions:
            return True
        return False

    def has_role(self, role: Union[str, Role]) -> bool:
        """Check if identity is assigned a specific role directly or via admin privilege."""
        role_str = role.value if isinstance(role, Role) else str(role).upper()
        return self.is_admin() or role_str in self.roles


class RolePolicyEngine:
    """Institutional Role & Attribute Policy Engine evaluating permissions dynamically."""

    @staticmethod
    def get_effective_permissions(identity: UserIdentity) -> Set[str]:
        """Use permission grants resolved from the centralized dynamic role allocation protocol."""
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        effective: Set[str] = set(identity.permissions)
        dynamic_perms = dynamic_role_protocol.get_effective_permissions(identity.roles, user_id=identity.username)
        effective.update(dynamic_perms)
        if identity.is_admin():
            effective.add("*")
        return effective

    @classmethod
    def has_permission(cls, identity: UserIdentity, required_permission: str) -> bool:
        """Evaluate if an identity satisfies a required permission pattern (e.g. wildcard matching)."""
        if identity.is_admin():
            return True

        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        if dynamic_role_protocol.has_permission(identity, required_permission):
            return True

        effective = cls.get_effective_permissions(identity)
        if "*" in effective:
            return True

        req_parts = required_permission.lower().split(":")

        for perm in effective:
            perm_lower = perm.lower()
            if perm_lower == "*" or perm_lower == required_permission.lower():
                return True
            if perm_lower.endswith(":*"):
                prefix = perm_lower[:-2]
                if required_permission.lower().startswith(prefix):
                    return True
            permission_parts = perm_lower.split(":")
            if len(permission_parts) == len(req_parts) and all(
                allowed == "*" or allowed == requested
                for allowed, requested in zip(permission_parts, req_parts)
            ):
                return True

        return False

    @classmethod
    def is_sandbox_accessible(cls, sandbox: dict, identity: UserIdentity) -> bool:
        """Evaluate if identity can execute inside target sandbox.
        Checks both caller permissions AND strict instance ownership/tenant isolation.
        """
        if identity.is_admin():
            return True

        # Check tenant isolation
        sbx_tenant = sandbox.get("tenant_id")
        if sbx_tenant and identity.tenant_id != "*" and sbx_tenant != identity.tenant_id:
            logger.warning(
                f"Tenant isolation mismatch: sandbox tenant '{sbx_tenant}' vs identity tenant '{identity.tenant_id}'"
            )
            return False

        owner = sandbox.get("owner")
        if not owner:
            # Missing ownership metadata must not turn an object reference into
            # a tenant-wide capability. Administrators bypass above; all
            # other callers require an explicit owner to match.
            return False

        allowed = {identity.username, identity.key_id}.union(GLOBAL_SANDBOX_OWNERS)
        if identity.metadata and "key_id" in identity.metadata:
            allowed.add(identity.metadata["key_id"])
        if identity.metadata and identity.metadata.get("workspace_id"):
            allowed.add(str(identity.metadata["workspace_id"]))

        return owner in allowed


# Backward compatibility wrapper functions
def is_admin_user(user: Union[dict, UserIdentity]) -> bool:
    if isinstance(user, UserIdentity):
        return user.is_admin()
    return UserIdentity.from_dict(user).is_admin()


def is_sandbox_accessible(sandbox: dict, user: Union[dict, UserIdentity]) -> bool:
    identity = user if isinstance(user, UserIdentity) else UserIdentity.from_dict(user)
    return RolePolicyEngine.is_sandbox_accessible(sandbox, identity)
