"""Role & Permission Mapping Repository using ThinkDome ORM."""

from __future__ import annotations

from typing import Optional, List, Set
from thinkdome.security.repositories.base import BaseRepository
from thinkdome.security.rbac.models import (
    Role,
    Permission,
    UserRole,
    RolePermission,
    UserPermission,
)


class RoleRepository(BaseRepository[Role]):
    """Repository handling database operations for Role entities and mappings."""

    def __init__(self) -> None:
        super().__init__(Role)

    def get_by_name(self, name: str) -> Optional[Role]:
        """Fetch role record by role name."""
        return self.find_one_by(name=name)

    def get_user_roles(self, user_id: str) -> List[Role]:
        """Fetch all active Role entities assigned to a user directly or via Role Profile."""
        role_ids = set()
        mappings = UserRole.query().filter(user_id=user_id).all()
        for m in mappings:
            role_ids.add(m.role_id)

        # Incorporate low-level role names collected by assigned Role Profile(s)
        try:
            import json
            from thinkdome.security.rbac.models import User, UserRoleProfile, RoleProfile
            user = User.get(user_id)
            if user:
                profile_ids = set()
                if getattr(user, "role_profile_id", None):
                    profile_ids.add(user.role_profile_id)
                if getattr(user, "role_profile_name", None):
                    prof_by_name = RoleProfile.query().filter(name=user.role_profile_name).first()
                    if prof_by_name:
                        profile_ids.add(prof_by_name.id)

                for urp in UserRoleProfile.query().filter(user_id=user_id).all():
                    profile_ids.add(urp.profile_id)

                for pid in profile_ids:
                    p = RoleProfile.get(pid)
                    if p and p.is_active:
                        for rid in json.loads(p.role_ids_json or "[]"):
                            role_ids.add(rid)
                        for rname in json.loads(getattr(p, "role_names_json", "[]") or "[]"):
                            r_obj = Role.query().filter(name=str(rname).upper()).first()
                            if r_obj:
                                role_ids.add(r_obj.id)
        except Exception:
            pass

        if not role_ids:
            return []
        # One set-based ORM query replaces an N+1 role lookup sequence.
        return [role for role in Role.query().filter(id__in=list(role_ids)).all() if role.is_active]

    def assign_role_to_user(self, user_id: str, role_id: str) -> UserRole:
        """Create mapping linking user to role."""
        existing = UserRole.query().filter(user_id=user_id, role_id=role_id).first()
        if existing:
            return existing
        mapping = UserRole(user_id=user_id, role_id=role_id)
        mapping.save()
        return mapping

    def remove_role_from_user(self, user_id: str, role_id: str) -> bool:
        """Remove user-to-role mapping link."""
        existing = UserRole.query().filter(user_id=user_id, role_id=role_id).first()
        if existing:
            existing.delete(soft=False)
            return True
        return False

    def get_role_permissions(self, role_id: str) -> List[Permission]:
        """Fetch all Permission catalog entities mapped to a role."""
        mappings = RolePermission.query().filter(role_id=role_id).all()
        perm_ids = [m.permission_id for m in mappings]
        perms = []
        for pid in perm_ids:
            p = Permission.get(pid)
            if p:
                perms.append(p)
        return perms

    def assign_permission_to_role(self, role_id: str, permission_id: str) -> RolePermission:
        """Link a permission to a role."""
        existing = RolePermission.query().filter(role_id=role_id, permission_id=permission_id).first()
        if existing:
            return existing
        mapping = RolePermission(role_id=role_id, permission_id=permission_id)
        mapping.save()
        return mapping

    def remove_permission_from_role(self, role_id: str, permission_id: str) -> bool:
        """Unlink a permission from a role."""
        existing = RolePermission.query().filter(role_id=role_id, permission_id=permission_id).first()
        if existing:
            existing.delete(soft=False)
            return True
        return False

    def get_inherited_role_ids(self, role_id: str) -> Set[str]:
        """Traverse role hierarchy parent pointers recursively."""
        inherited: Set[str] = {role_id}
        current = self.get_by_id(role_id)
        while current and current.parent_role_id:
            parent_id = current.parent_role_id
            if parent_id in inherited:
                break  # Cycle detection
            inherited.add(parent_id)
            current = self.get_by_id(parent_id)
        return inherited
