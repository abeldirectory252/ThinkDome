"""Permission Catalog Repository using ThinkDome ORM."""

from __future__ import annotations

from typing import Optional, List
from thinkdome.repositories.base_repository import BaseRepository
from thinkdome.models.rbac_models import Permission, UserPermission


class PermissionRepository(BaseRepository[Permission]):
    """Repository managing Permission catalog and direct user permission overrides."""

    def __init__(self) -> None:
        super().__init__(Permission)

    def find_by_tuple(self, module: str, resource: str, action: str) -> Optional[Permission]:
        """Fetch Permission record by exact module, resource, and action."""
        return self.find_one_by(module=module, resource=resource, action=action)

    def get_direct_user_permissions(self, user_id: str) -> List[tuple[Permission, bool]]:
        """Fetch explicit direct permission grants/denials for a user."""
        mappings = UserPermission.query().filter(user_id=user_id).all()
        result = []
        for m in mappings:
            p = self.get_by_id(m.permission_id)
            if p:
                result.append((p, bool(m.granted)))
        return result

    def grant_direct_permission(self, user_id: str, permission_id: str, granted: bool = True) -> UserPermission:
        """Grant or deny a direct permission override to a user."""
        existing = UserPermission.query().filter(user_id=user_id, permission_id=permission_id).first()
        if existing:
            existing._values["granted"] = granted
            existing.save()
            return existing
        mapping = UserPermission(user_id=user_id, permission_id=permission_id, granted=granted)
        mapping.save()
        return mapping
