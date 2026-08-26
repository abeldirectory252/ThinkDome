"""Enterprise RBAC ORM Models mapped natively to ThinkDome custom ORM."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    BooleanField,
    SelectField,
)


class User(Model):
    """User account entity."""
    __tablename__ = "rbac_users"

    username = StringField(required=True, indexed=True, unique=True)
    email = StringField(required=True, indexed=True, unique=True)
    password_hash = StringField(required=True)
    status = SelectField(choices=["active", "disabled", "deactivated", "pending"], default="active")
    last_login = StringField()


class UserProfile(Model):
    """User Profile entity linked 1-to-1 with User."""
    __tablename__ = "rbac_profiles"

    user_id = StringField(required=True)
    first_name = StringField(default="")
    last_name = StringField(default="")
    phone = StringField(default="")
    department_id = StringField()
    designation = StringField(default="")
    avatar_url = StringField(default="")


class Role(Model):
    """Dynamic Role entity supporting hierarchy."""
    __tablename__ = "rbac_roles"

    name = StringField(required=True, indexed=True, unique=True)
    description = StringField(default="")
    parent_role_id = StringField()
    is_active = BooleanField(default=True)
    is_system = BooleanField(default=False)


class RoleProfile(Model):
    """Reusable bundle of roles assigned to a user by administrators."""
    __tablename__ = "rbac_role_profiles"

    name = StringField(required=True, indexed=True, unique=True)
    description = StringField(default="")
    role_ids_json = StringField(default="[]")
    is_active = BooleanField(default=True)


class Permission(Model):
    """Granular Permission catalog item."""
    __tablename__ = "rbac_permissions"

    module = StringField(required=True)
    resource = StringField(required=True)
    action = SelectField(
        choices=[
            "create", "read", "update", "delete", "export",
            "print", "submit", "cancel", "approve", "reject",
            "share", "import", "custom"
        ],
        required=True
    )
    description = StringField(default="")


class UserRole(Model):
    """Many-to-Many mapping between User and Role."""
    __tablename__ = "rbac_user_roles"

    user_id = StringField(required=True, indexed=True)
    role_id = StringField(required=True, indexed=True)


class RolePermission(Model):
    """Many-to-Many mapping between Role and Permission."""
    __tablename__ = "rbac_role_permissions"

    role_id = StringField(required=True)
    permission_id = StringField(required=True)


class UserPermission(Model):
    """Direct User Permission override mapping."""
    __tablename__ = "rbac_user_permissions"

    user_id = StringField(required=True)
    permission_id = StringField(required=True)
    granted = BooleanField(default=True)


class Department(Model):
    """Department entity."""
    __tablename__ = "rbac_departments"

    name = StringField(required=True)
    description = StringField(default="")
    parent_department_id = StringField()


class UserGroup(Model):
    """User Group entity."""
    __tablename__ = "rbac_user_groups"

    name = StringField(required=True)
    description = StringField(default="")


class GroupMember(Model):
    """User Group membership mapping."""
    __tablename__ = "rbac_group_members"

    group_id = StringField(required=True)
    user_id = StringField(required=True)


class GroupRole(Model):
    """User Group role mapping."""
    __tablename__ = "rbac_group_roles"

    group_id = StringField(required=True)
    role_id = StringField(required=True)


class RbacAuditLog(Model):
    """RBAC Audit Trail entry."""
    __tablename__ = "rbac_audit_logs"

    actor = StringField(required=True)
    action = StringField(required=True)
    target_type = StringField(required=True)
    target_id = StringField()
    details = StringField(default="{}")
    ip_address = StringField(default="127.0.0.1")


class LoginHistory(Model):
    """User Login Audit Log."""
    __tablename__ = "rbac_login_histories"

    user_id = StringField(required=True)
    ip_address = StringField(default="127.0.0.1")
    user_agent = StringField(default="")
    status = SelectField(choices=["success", "failed", "blocked"], default="success")


class RefreshToken(Model):
    """JWT Refresh Token store."""
    __tablename__ = "rbac_refresh_tokens"

    user_id = StringField(required=True)
    token_hash = StringField(required=True)
    expires_at = StringField(required=True)
    revoked = BooleanField(default=False)


class Session(Model):
    """Active Session Store."""
    __tablename__ = "rbac_sessions"

    user_id = StringField(required=True)
    session_token = StringField(required=True)
    ip_address = StringField(default="127.0.0.1")
    device_info = StringField(default="")
    expires_at = StringField(required=True)
