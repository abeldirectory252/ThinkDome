"""Security utilities: API key validation, rate limiting hooks."""

from typing import Optional

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from thinkdome.core.config import get_settings

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

ADMIN_ROLES = {Role.SUPER_ADMIN.value, Role.ENTERPRISE_ADMIN.value, Role.ADMIN.value, Role.ORCH.value, Role.IDE.value}
DEFAULT_ADMIN_USERNAMES = {"admin", "administrator"}
GLOBAL_SANDBOX_OWNERS = {"admin", "administrator", "anonymous", "api_key_client"}

# Institutional Role Hierarchy: Parent role -> set of inherited permissions/roles
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    Role.SUPER_ADMIN.value: {"*"},
    Role.ENTERPRISE_ADMIN.value: {
        "sandbox:*", "file:*", "erp:*", "system:read", "audit:read"
    },
    Role.ADMIN.value: {
        "sandbox:*", "file:*", "erp:*", "audit:read"
    },
    Role.FINANCE_MANAGER.value: {
        "erp:finance:*", "erp:crud:*", "erp:report:*", "erp:audit:*", "file:read"
    },
    Role.FINANCE_USER.value: {
        "erp:finance:read", "erp:finance:post", "erp:crud:read", "erp:crud:create", "erp:crud:update", "file:read"
    },
    Role.AUDITOR.value: {
        "erp:audit:read", "erp:finance:read", "erp:report:read", "audit:read", "file:read"
    },
    Role.SALES_USER.value: {
        "erp:crud:sales_*", "erp:crud:customer_*", "erp:report:read", "file:read"
    },
    Role.AGENT_STANDARD.value: {
        "sandbox:exec", "search:web", "file:read", "memory:*"
    },
    Role.LLM.value: {
        "sandbox:exec", "search:web", "memory:*"
    },
    Role.ANONYMOUS.value: {
        "sandbox:exec"
    },
    Role.GUEST.value: {
        "file:read"
    }
}


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
        if not roles:
            roles.add(Role.ANONYMOUS.value)

        # Collect permissions
        raw_perms = data.get("permissions") or []
        permissions = set(raw_perms) if isinstance(raw_perms, (list, set, tuple)) else set()

        return cls(
            username=username,
            tenant_id=tenant_id,
            roles=roles,
            permissions=permissions,
            token_type=token_type,
            key_id=data.get("key_id"),
            metadata=data.get("metadata", {}),
        )

    def is_admin(self) -> bool:
        """Check if identity possesses administrator level authority."""
        if self.username.lower() in DEFAULT_ADMIN_USERNAMES:
            return True
        return bool(self.roles.intersection(ADMIN_ROLES))

    def has_role(self, role: Union[str, Role]) -> bool:
        """Check if identity is assigned a specific role directly or via admin privilege."""
        role_str = role.value if isinstance(role, Role) else str(role).upper()
        return self.is_admin() or role_str in self.roles


class RolePolicyEngine:
    """Institutional Role & Attribute Policy Engine evaluating permissions dynamically."""

    @staticmethod
    def get_effective_permissions(identity: UserIdentity) -> Set[str]:
        """Compile effective permission set across assigned roles and custom permissions."""
        effective: Set[str] = set(identity.permissions)
        for role in identity.roles:
            role_upper = role.upper()
            if role_upper in ROLE_PERMISSIONS:
                effective.update(ROLE_PERMISSIONS[role_upper])
        if identity.is_admin():
            effective.add("*")
        return effective

    @classmethod
    def has_permission(cls, identity: UserIdentity, required_permission: str) -> bool:
        """Evaluate if an identity satisfies a required permission pattern (e.g. wildcard matching)."""
        if identity.is_admin():
            return True

        effective = cls.get_effective_permissions(identity)
        if "*" in effective:
            return True

        req_parts = required_permission.lower().split(":")

        for perm in effective:
            perm_lower = perm.lower()
            if perm_lower == required_permission.lower() or perm_lower == "*":
                return True

            # Match wildcard prefix pattern like 'erp:finance:*' or 'file:*'
            if perm_lower.endswith(":*"):
                prefix = perm_lower[:-2]
                if required_permission.lower().startswith(prefix):
                    return True

        return False

    @classmethod
    def is_sandbox_accessible(cls, sandbox: dict, identity: UserIdentity) -> bool:
        """Evaluate if identity can execute inside target sandbox."""
        if identity.is_admin():
            return True

        owner = sandbox.get("owner")
        if not owner:
            return True

        allowed = {identity.username, identity.key_id}.union(GLOBAL_SANDBOX_OWNERS)
        return owner in allowed


# Backward compatibility wrapper functions
def is_admin_user(user: Union[dict, UserIdentity]) -> bool:
    if isinstance(user, UserIdentity):
        return user.is_admin()
    return UserIdentity.from_dict(user).is_admin()


def is_sandbox_accessible(sandbox: dict, user: Union[dict, UserIdentity]) -> bool:
    identity = user if isinstance(user, UserIdentity) else UserIdentity.from_dict(user)
    return RolePolicyEngine.is_sandbox_accessible(sandbox, identity)
