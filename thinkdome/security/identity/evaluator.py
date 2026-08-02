"""7-Level Dynamic Permission Evaluator Engine."""

from __future__ import annotations

import logging
from typing import Set, Optional
from thinkdome.security.identity.core import UserIdentity, ROLE_ADMIN
from thinkdome.security.repositories.user import UserRepository
from thinkdome.security.repositories.role import RoleRepository
from thinkdome.security.repositories.permission import PermissionRepository
from thinkdome.security.identity.cache import permission_cache
from thinkdome.security.rbac.models import UserGroup, GroupMember, GroupRole, UserProfile, Department

logger = logging.getLogger(__name__)


class PermissionEvaluator:
    """Evaluates dynamic user permissions using 7-level resolution hierarchy with caching."""

    def __init__(self) -> None:
        self.user_repo = UserRepository()
        self.role_repo = RoleRepository()
        self.perm_repo = PermissionRepository()

    def get_effective_permissions(self, user_id: str) -> Set[str]:
        """Compile effective permissions across all 7 evaluation levels."""
        cached = permission_cache.get(user_id)
        if cached is not None:
            return cached

        user = self.user_repo.get_by_id(user_id)
        if not user or user.status != "active":
            return set()

        effective_perms: Set[str] = set()

        # ── Level 1: Super Admin check ───────────────────────────────────────
        user_roles = self.role_repo.get_user_roles(user_id)
        role_names = {r.name.upper() for r in user_roles}
        if "SUPER_ADMIN" in role_names or "ADMIN" in role_names or user.username.lower() in ("admin", "administrator"):
            effective_perms.add("*")
            permission_cache.set(user_id, effective_perms)
            return effective_perms

        # ── Level 2: Direct User Permissions (Explicit Grants / Denials) ─────
        direct_perms = self.perm_repo.get_direct_user_permissions(user_id)
        explicit_denies: Set[str] = set()
        for perm, granted in direct_perms:
            p_str = f"{perm.module}:{perm.resource}:{perm.action}".lower()
            if granted:
                effective_perms.add(p_str)
            else:
                explicit_denies.add(p_str)

        # ── Level 3 & Level 4: Direct Assigned Roles & Inherited Parent Roles ──
        all_role_ids: Set[str] = set()
        for role in user_roles:
            all_role_ids.update(self.role_repo.get_inherited_role_ids(role.id))

        for role_id in all_role_ids:
            perms = self.role_repo.get_role_permissions(role_id)
            for p in perms:
                p_str = f"{p.module}:{p.resource}:{p.action}".lower()
                if p_str not in explicit_denies:
                    effective_perms.add(p_str)

        # ── Level 5: User Group Permissions ─────────────────────────────────
        group_memberships = GroupMember.query().filter(user_id=user_id).all()
        for gm in group_memberships:
            group_roles = GroupRole.query().filter(group_id=gm.group_id).all()
            for gr in group_roles:
                inherited_group_roles = self.role_repo.get_inherited_role_ids(gr.role_id)
                for rid in inherited_group_roles:
                    perms = self.role_repo.get_role_permissions(rid)
                    for p in perms:
                        p_str = f"{p.module}:{p.resource}:{p.action}".lower()
                        if p_str not in explicit_denies:
                            effective_perms.add(p_str)

        # ── Level 6: Department Permissions ─────────────────────────────────
        profile = self.user_repo.get_profile(user_id)
        if profile and profile.department_id:
            effective_perms.add(f"department:{profile.department_id}:read".lower())

        # ── Level 7: Default Permissions ─────────────────────────────────────
        effective_perms.add("public:read")

        # Cache resolved permissions
        permission_cache.set(user_id, effective_perms)
        return effective_perms

    def has_permission(self, user_id: str, module: str, resource: str, action: str) -> bool:
        """Check if user has required module:resource:action permission."""
        effective = self.get_effective_permissions(user_id)
        if "*" in effective:
            return True

        target = f"{module}:{resource}:{action}".lower()
        if target in effective:
            return True

        # Wildcard patterns e.g. 'erp:finance:*' or 'file:*'
        resource_wildcard = f"{module}:{resource}:*".lower()
        module_wildcard = f"{module}:*:*".lower()

        return resource_wildcard in effective or module_wildcard in effective

    def has_role(self, user_id: str, role_name: str) -> bool:
        """Check if user is directly or hierarchically assigned a role by name."""
        user_roles = self.role_repo.get_user_roles(user_id)
        all_role_ids: Set[str] = set()
        for r in user_roles:
            all_role_ids.update(self.role_repo.get_inherited_role_ids(r.id))

        for rid in all_role_ids:
            role = self.role_repo.get_by_id(rid)
            if role and role.name.upper() == role_name.upper():
                return True
        return False


# Global evaluator singleton
permission_evaluator = PermissionEvaluator()
