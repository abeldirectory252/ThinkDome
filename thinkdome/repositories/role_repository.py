"""Role & Permission Mapping Repository using ThinkDome ORM."""

from __future__ import annotations

from typing import Optional, List, Set
from thinkdome.repositories.base_repository import BaseRepository
from thinkdome.models.rbac_models import (
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
        """Fetch all active Role entities assigned to a user."""
        mappings = UserRole.query().filter(user_id=user_id).all()
        role_ids = [m.role_id for m in mappings]
        roles = []
        for rid in role_ids:
            r = self.get_by_id(rid)
            if r and r._values.get("is_active", True):
                roles.append(r)
        return roles

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
