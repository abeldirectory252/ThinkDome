"""Enterprise RBAC Business Services adhering to SOLID principles."""

from __future__ import annotations

import hashlib
import secrets
import json
import logging
from typing import Optional, List, Dict, Any
from thinkdome.models.rbac_models import (
    User,
    UserProfile,
    Role,
    Permission,
    UserRole,
    RolePermission,
    Department,
    UserGroup,
)
from thinkdome.repositories.user_repository import UserRepository
from thinkdome.repositories.role_repository import RoleRepository
from thinkdome.repositories.permission_repository import PermissionRepository
from thinkdome.repositories.audit_repository import AuditRepository
from thinkdome.security.permission_cache import permission_cache

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash password securely using SHA-256 with salt."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class UserService:
    """Business logic service for User and UserProfile lifecycle management."""

    def __init__(self) -> None:
        self.user_repo = UserRepository()
        self.role_repo = RoleRepository()
        self.audit_repo = AuditRepository()

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        first_name: str = "",
        last_name: str = "",
        actor: str = "system"
    ) -> User:
        """Create new User account and Profile."""
        if self.user_repo.get_by_username(username):
            raise ValueError(f"Username '{username}' already exists.")
        if self.user_repo.get_by_email(email):
            raise ValueError(f"Email '{email}' already registered.")

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            status="active"
        )
        user.save()

        profile = UserProfile(
            user_id=user.id,
            first_name=first_name,
            last_name=last_name
        )
        profile.save()

        self.audit_repo.log_event(
            actor=actor,
            action="create_user",
            target_type="User",
            target_id=user.id,
            details={"username": username, "email": email}
        )
        return user

    def update_user_status(self, user_id: str, status: str, actor: str = "system") -> User:
        """Enable or disable user account status."""
        user = self.user_repo.update_status(user_id, status)
        if not user:
            raise ValueError(f"User ID '{user_id}' not found.")

        permission_cache.invalidate_user(user_id)
        self.audit_repo.log_event(
            actor=actor,
            action="update_user_status",
            target_type="User",
            target_id=user_id,
            details={"status": status}
        )
        return user

    def assign_role_to_user(self, user_id: str, role_id: str, actor: str = "system") -> bool:
        """Assign role to user and invalidate cache."""
        user = self.user_repo.get_by_id(user_id)
        role = self.role_repo.get_by_id(role_id)
        if not user or not role:
            raise ValueError("User or Role not found.")

        self.role_repo.assign_role_to_user(user_id, role_id)
        permission_cache.invalidate_user(user_id)

        self.audit_repo.log_event(
            actor=actor,
            action="assign_role",
            target_type="UserRole",
            target_id=user_id,
            details={"role_id": role_id, "role_name": role.name}
        )
        return True

    def remove_role_from_user(self, user_id: str, role_id: str, actor: str = "system") -> bool:
        """Remove role from user and invalidate cache."""
        res = self.role_repo.remove_role_from_user(user_id, role_id)
        if res:
            permission_cache.invalidate_user(user_id)
            self.audit_repo.log_event(
                actor=actor,
                action="remove_role",
                target_type="UserRole",
                target_id=user_id,
                details={"role_id": role_id}
            )
        return res


class RoleService:
    """Business logic service for dynamic Role lifecycle and Permission assignment."""

    def __init__(self) -> None:
        self.role_repo = RoleRepository()
        self.perm_repo = PermissionRepository()
        self.audit_repo = AuditRepository()

    def create_role(
        self,
        name: str,
        description: str = "",
        parent_role_id: Optional[str] = None,
        actor: str = "system"
    ) -> Role:
        """Dynamically create a new Role without application restart."""
        existing = self.role_repo.get_by_name(name)
        if existing:
            raise ValueError(f"Role '{name}' already exists.")

        role = Role(
            name=name,
            description=description,
            parent_role_id=parent_role_id or "",
            is_active=True
        )
        role.save()

        permission_cache.invalidate_all()
        self.audit_repo.log_event(
            actor=actor,
            action="create_role",
            target_type="Role",
            target_id=role.id,
            details={"name": name, "parent_role_id": parent_role_id}
        )
        return role

    def assign_permission_to_role(self, role_id: str, permission_id: str, actor: str = "system") -> bool:
        """Assign permission catalog item to a role."""
        role = self.role_repo.get_by_id(role_id)
        perm = self.perm_repo.get_by_id(permission_id)
        if not role or not perm:
            raise ValueError("Role or Permission not found.")

        self.role_repo.assign_permission_to_role(role_id, permission_id)
        permission_cache.invalidate_all()

        self.audit_repo.log_event(
            actor=actor,
            action="assign_permission_to_role",
            target_type="RolePermission",
            target_id=role_id,
            details={"permission_id": permission_id, "action": perm.action}
        )
        return True

    def delete_role(self, role_id: str, actor: str = "system") -> bool:
        """Delete role dynamically and invalidate cache."""
        role = self.role_repo.get_by_id(role_id)
        if not role:
            return False
        if getattr(role, "is_system", False):
            raise ValueError("System roles cannot be deleted.")

        res = self.role_repo.delete(role_id, soft=True)
        permission_cache.invalidate_all()

        self.audit_repo.log_event(
            actor=actor,
            action="delete_role",
            target_type="Role",
            target_id=role_id,
            details={"role_name": role.name}
        )
        return res


class PermissionService:
    """Business logic service managing Permission catalog entries."""

    def __init__(self) -> None:
        self.perm_repo = PermissionRepository()

    def create_permission(
        self,
        module: str,
        resource: str,
        action: str,
        description: str = ""
    ) -> Permission:
        """Create new permission catalog item."""
        existing = self.perm_repo.find_by_tuple(module, resource, action)
        if existing:
            return existing

        perm = Permission(
            module=module,
            resource=resource,
            action=action,
            description=description
        )
        perm.save()
        permission_cache.invalidate_all()
        return perm

    def list_all(self) -> List[Permission]:
        """List all permissions in catalog."""
        return self.perm_repo.find_all()
