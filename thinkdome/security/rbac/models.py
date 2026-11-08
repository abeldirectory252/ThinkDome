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
    role_profile_id = StringField(default="")
    role_profile_name = StringField(default="")


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
    organization = StringField(default="")
    bio = StringField(default="")
    timezone = StringField(default="UTC")
    locale = StringField(default="en-US")


class Role(Model):
    """Dynamic Role entity representing a low-level Role Name holding low-level privileges."""
    __tablename__ = "rbac_roles"

    name = StringField(required=True, indexed=True, unique=True)
    description = StringField(default="")
    parent_role_id = StringField()
    is_admin = BooleanField(default=False)
    is_active = BooleanField(default=True)
    is_system = BooleanField(default=False)


class RoleProfile(Model):
    """Reusable collection/bundle of Role Names easily assigned to users."""
    __tablename__ = "rbac_role_profiles"

    name = StringField(required=True, indexed=True, unique=True)
    description = StringField(default="")
    role_ids_json = StringField(default="[]")
    role_names_json = StringField(default="[]")
    is_active = BooleanField(default=True)
    is_default = BooleanField(default=False)


class RoleProfileRole(Model):
    """Many-to-Many mapping between RoleProfile and low-level Role Name."""
    __tablename__ = "rbac_role_profile_roles"

    profile_id = StringField(required=True, indexed=True)
    role_id = StringField(required=True, indexed=True)


class UserRoleProfile(Model):
    """Many-to-Many mapping between User and RoleProfile."""
    __tablename__ = "rbac_user_role_profiles"

    user_id = StringField(required=True, indexed=True)
    profile_id = StringField(required=True, indexed=True)


class Permission(Model):
    """Granular Permission catalog item."""
    __tablename__ = "rbac_permissions"

    module = StringField(required=True)
    resource = StringField(required=True)
    action = SelectField(
        choices=[
            "*", "create", "read", "update", "delete", "execute",
            "export",
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


class ApiKey(Model):
    """API Key credential entity mapped natively via ThinkDome ORM."""
    __tablename__ = "api_keys"
    __primary_key__ = "token"
    __omit_soft_delete__ = True

    token = StringField(primary_key=True)
    key_id = StringField(required=True, indexed=True)
    display_name = StringField(default="Unnamed API Key")
    token_type = StringField(default="API_KEY")
    created_at = StringField()
    expires_at = StringField()
    status = StringField(default="active")
    masked_token = StringField(default="")


class AuthUser(Model):
    """Authentication user credential entity mapped natively to `users` table via ThinkDome ORM."""
    __tablename__ = "users"
    __primary_key__ = "username"
    __omit_soft_delete__ = True

    username = StringField(primary_key=True)
    hashed_password = StringField(required=True)
    salt = StringField(required=True)
    created_at = StringField()
    role_profile_name = StringField(default="")


class AuthRefreshToken(Model):
    """Authentication refresh token entity mapped natively to `refresh_tokens` table via ThinkDome ORM."""
    __tablename__ = "refresh_tokens"
    __primary_key__ = "token_hash"
    __omit_soft_delete__ = True

    token_hash = StringField(primary_key=True)
    username = StringField(required=True)
    created_at = StringField()
    expires_at = StringField(required=True)
    status = StringField(default="active")


class CredentialVaultEntry(Model):
    """Encrypted credential vault secret mapped natively to `credential_vault` table via ThinkDome ORM."""
    __tablename__ = "credential_vault"
    __primary_key__ = "id"
    __omit_soft_delete__ = True

    id = IntegerField(primary_key=True)
    user_id = StringField(required=True, indexed=True)
    sandbox_id = StringField(required=True, indexed=True)
    key_name = StringField(required=True, indexed=True)
    encrypted_value = StringField(required=True)
    created_at = StringField()
    updated_at = StringField()


class ApiKeyPermission(Model):
    """Workspace permission granted to one API credential."""
    __tablename__ = "rbac_api_key_permissions"

    key_id = StringField(required=True, indexed=True)
    permission_id = StringField(required=True, indexed=True)


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


class DocPerm(Model):
    """Dynamic Document Permission rule representing centralized dynamic role allocation.

    Properties:
    - document_type: target document or entity type (Page, Sidebar, Sandbox, Console, IDE, Filebox, NetworkEgress, MCPTool, ModelDesign, etc.)
    - role: assigned role name (e.g. SUPER_ADMIN, ADMIN, DEVELOPER, AUDITOR, etc.)
    - level: permission level hierarchy (0 = document level, 1+ = field level / privileged level)
    - permissions (14 granular actions):
        - perm_select: bool (Select)
        - perm_read: bool (Read)
        - perm_write: bool (Write)
        - perm_create: bool (Create)
        - perm_delete: bool (Delete)
        - perm_print: bool (Print)
        - perm_email: bool (Email)
        - perm_report: bool (Report)
        - perm_import: bool (Import)
        - perm_export: bool (Export)
        - perm_set_user_permissions: bool (Set User Permissions)
        - perm_share: bool (Share)
        - perm_access_mcp: bool (Access MCP)
        - perm_file_related: bool (File Related)
    - granter & denial:
        - is_denial: bool (if True, this is an explicit Privilege Denial which takes strict precedence)
        - user_id: string (optional user-specific override)
        - workspace_id: string (optional workspace scoping)
        - is_custom_exempt: bool (if True, intentionally bypasses/exempts privilege check)
    """
    __tablename__ = "rbac_doc_perms"

    document_type = StringField(required=True, indexed=True)
    role = StringField(required=True, indexed=True)
    level = IntegerField(default=0)

    # 14 dynamic permissions
    perm_select = BooleanField(default=False)
    perm_read = BooleanField(default=False)
    perm_write = BooleanField(default=False)
    perm_create = BooleanField(default=False)
    perm_delete = BooleanField(default=False)
    perm_print = BooleanField(default=False)
    perm_email = BooleanField(default=False)
    perm_report = BooleanField(default=False)
    perm_import = BooleanField(default=False)
    perm_export = BooleanField(default=False)
    perm_set_user_permissions = BooleanField(default=False)
    perm_share = BooleanField(default=False)
    perm_access_mcp = BooleanField(default=False)
    perm_file_related = BooleanField(default=False)

    is_denial = BooleanField(default=False)
    user_id = StringField(default="")
    workspace_id = StringField(default="")
    is_custom_exempt = BooleanField(default=False)

    def get_permissions(self) -> Dict[str, bool]:
        return {
            "select": bool(self.perm_select),
            "read": bool(self.perm_read),
            "write": bool(self.perm_write),
            "create": bool(self.perm_create),
            "delete": bool(self.perm_delete),
            "print": bool(self.perm_print),
            "email": bool(self.perm_email),
            "report": bool(self.perm_report),
            "import": bool(self.perm_import),
            "export": bool(self.perm_export),
            "set_user_permissions": bool(self.perm_set_user_permissions),
            "share": bool(self.perm_share),
            "access_mcp": bool(self.perm_access_mcp),
            "file_related": bool(self.perm_file_related),
        }

    def has_perm(self, action: str) -> bool:
        norm = action.strip().lower().replace("-", "_")
        if norm == "import":
            return bool(self.perm_import)
        field_name = f"perm_{norm}"
        if hasattr(self, field_name):
            return bool(getattr(self, field_name))
        if norm in ("execute", "exec", "custom"):
            return bool(self.perm_read and self.perm_write) or bool(self.perm_access_mcp)
        return False

