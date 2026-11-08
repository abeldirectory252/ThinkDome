"""Dynamic Role & Role Profile Registry.

Implements database-backed registration, Redis caching, and dynamic mapping
for Role Names (holding low-level privileges) and Role Profiles (collections of Role Names).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Union

from thinkdome.security.rbac.models import (
    Role,
    RoleProfile,
    RoleProfileRole,
    UserRoleProfile,
    UserRole,
    DocPerm,
    Permission,
    RolePermission,
    User,
    AuthUser,
)
from thinkdome.security.rbac.cache import rbac_cache

logger = logging.getLogger(__name__)


class RoleProfileRegistry:
    """Enterprise Registry managing Role Names, Role Profiles, and User Mappings."""

    _instance: Optional[RoleProfileRegistry] = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self.cache = rbac_cache
        self._initialized: bool = False

    @classmethod
    def get_instance(cls) -> RoleProfileRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Role (Role Name) Registration & Management ────────────────────────────

    def register_role(
        self,
        name: str,
        description: str = "",
        is_admin: bool = False,
        parent_role: Optional[str] = None,
        is_system: bool = False,
        doc_perms: Optional[List[Dict[str, Any]]] = None,
        permissions: Optional[List[str]] = None,
    ) -> Role:
        """Register or update a low-level Role Name in DB and cache it on Redis."""
        norm_name = str(name).strip().upper()
        if not norm_name:
            raise ValueError("Role name cannot be empty")

        parent_role_id = None
        if parent_role:
            parent_norm = str(parent_role).strip().upper()
            p_obj = Role.query().filter(name=parent_norm).first()
            if p_obj:
                parent_role_id = p_obj.id

        role = Role.query().filter(name=norm_name).first()
        if role:
            role.description = description or role.description
            role.is_admin = bool(is_admin or role.is_admin)
            if parent_role_id:
                role.parent_role_id = parent_role_id
            role.is_active = True
            role.save()
        else:
            role = Role(
                name=norm_name,
                description=description,
                parent_role_id=parent_role_id,
                is_admin=bool(is_admin),
                is_active=True,
                is_system=bool(is_system),
            )
            role.save()

        # Seed/Attach low-level DocPerm privileges if provided
        if doc_perms:
            for dp in doc_perms:
                doc_type = dp.get("document_type")
                if not doc_type:
                    continue
                level = dp.get("level", 0)
                existing_dp = DocPerm.query().filter(document_type=doc_type, role=norm_name, level=level).first()
                if not existing_dp:
                    new_dp = DocPerm(
                        document_type=doc_type,
                        role=norm_name,
                        level=level,
                        perm_select=bool(dp.get("perm_select", False)),
                        perm_read=bool(dp.get("perm_read", False)),
                        perm_write=bool(dp.get("perm_write", False)),
                        perm_create=bool(dp.get("perm_create", False)),
                        perm_delete=bool(dp.get("perm_delete", False)),
                        perm_print=bool(dp.get("perm_print", False)),
                        perm_email=bool(dp.get("perm_email", False)),
                        perm_report=bool(dp.get("perm_report", False)),
                        perm_import=bool(dp.get("perm_import", False)),
                        perm_export=bool(dp.get("perm_export", False)),
                        perm_set_user_permissions=bool(dp.get("perm_set_user_permissions", False)),
                        perm_share=bool(dp.get("perm_share", False)),
                        perm_access_mcp=bool(dp.get("perm_access_mcp", False)),
                        perm_file_related=bool(dp.get("perm_file_related", False)),
                        is_denial=bool(dp.get("is_denial", False)),
                        is_custom_exempt=bool(dp.get("is_custom_exempt", False)),
                    )
                    new_dp.save()

        # Attach granular permissions if provided
        if permissions:
            for perm_val in permissions:
                parts = perm_val.split(":")
                if len(parts) == 3:
                    mod, res, act = parts
                    perm_record = Permission.query().filter(module=mod, resource=res, action=act).first()
                    if not perm_record:
                        perm_record = Permission(module=mod, resource=res, action=act)
                        perm_record.save()
                    if not RolePermission.query().filter(role_id=role.id, permission_id=perm_record.id).first():
                        RolePermission(role_id=role.id, permission_id=perm_record.id).save()

        # Cache on Redis
        role_dict = {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "is_admin": bool(role.is_admin),
            "parent_role_id": role.parent_role_id,
            "is_active": bool(role.is_active),
            "is_system": bool(role.is_system),
        }
        self.cache.cache_role(norm_name, role_dict)
        self.cache.clear_prefix("user_roles:")
        return role

    def get_role(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve role metadata from Redis cache or database."""
        norm_name = str(name).strip().upper()
        cached = self.cache.get_role(norm_name)
        if cached:
            return cached
        r = Role.query().filter(name=norm_name).first()
        if r:
            role_dict = {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "is_admin": bool(r.is_admin),
                "parent_role_id": r.parent_role_id,
                "is_active": bool(r.is_active),
                "is_system": bool(r.is_system),
            }
            self.cache.cache_role(norm_name, role_dict)
            return role_dict
        return None

    # ── Role Profile Registration & Management ───────────────────────────────

    def register_role_profile(
        self,
        name: str,
        description: str = "",
        role_names: Optional[List[str]] = None,
        is_default: bool = False,
    ) -> RoleProfile:
        """Register or update a Role Profile (collection of Role Names) in DB and cache on Redis."""
        norm_name = str(name).strip()
        if not norm_name:
            raise ValueError("Role Profile name cannot be empty")

        clean_roles = [str(r).strip().upper() for r in (role_names or []) if str(r).strip()]
        
        # Resolve role IDs for clean roles
        role_ids = []
        for r_name in clean_roles:
            r_obj = Role.query().filter(name=r_name).first()
            if not r_obj:
                r_obj = self.register_role(name=r_name, description=f"Auto-registered role {r_name}")
            role_ids.append(r_obj.id)

        profile = RoleProfile.query().filter(name=norm_name).first()
        if profile:
            profile.description = description or profile.description
            profile.role_ids_json = json.dumps(role_ids)
            profile.role_names_json = json.dumps(clean_roles)
            profile.is_default = bool(is_default or profile.is_default)
            profile.is_active = True
            profile.save()
        else:
            profile = RoleProfile(
                name=norm_name,
                description=description,
                role_ids_json=json.dumps(role_ids),
                role_names_json=json.dumps(clean_roles),
                is_active=True,
                is_default=bool(is_default),
            )
            profile.save()

        # Update normalized mapping table RoleProfileRole
        try:
            RoleProfileRole.query().filter(profile_id=profile.id).delete(soft=False)
            for rid in role_ids:
                RoleProfileRole(profile_id=profile.id, role_id=rid).save()
        except Exception as e:
            logger.debug("RoleProfileRole mapping sync skipped: %s", e)

        # Cache on Redis
        profile_dict = {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "role_names": clean_roles,
            "role_ids": role_ids,
            "is_active": bool(profile.is_active),
            "is_default": bool(profile.is_default),
        }
        self.cache.cache_role_profile(norm_name, profile_dict)
        self.cache.clear_prefix("user_roles:")
        return profile

    def get_role_profile(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve Role Profile by name from Redis or database."""
        norm_name = str(name).strip()
        cached = self.cache.get_role_profile(norm_name)
        if cached:
            return cached

        p = RoleProfile.query().filter(name=norm_name).first()
        if not p:
            return None

        # Resolve role names
        names = []
        if getattr(p, "role_names_json", None):
            try:
                names = json.loads(p.role_names_json)
            except Exception:
                names = []
        if not names and getattr(p, "role_ids_json", None):
            try:
                r_ids = json.loads(p.role_ids_json)
                for rid in r_ids:
                    r = Role.get(rid)
                    if r:
                        names.append(r.name)
            except Exception:
                pass

        profile_dict = {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "role_names": names,
            "role_ids": json.loads(p.role_ids_json or "[]"),
            "is_active": bool(p.is_active),
            "is_default": bool(getattr(p, "is_default", False)),
        }
        self.cache.cache_role_profile(norm_name, profile_dict)
        return profile_dict

    # ── User to Role Profile Assignment ───────────────────────────────────────

    def assign_role_profile_to_user(
        self,
        username_or_id: str,
        profile_name_or_id: str,
    ) -> bool:
        """Assign a Role Profile (collection of Role Names) to a User."""
        target = str(username_or_id).strip().lower()
        user = User.query().filter(username=target).first()
        if not user:
            user = User.get(username_or_id)
        if not user:
            # Fallback search AuthUser
            auth_u = AuthUser.query().filter(username=target).first()
            if auth_u:
                auth_u.role_profile_name = profile_name_or_id
                auth_u.save()
            return False

        # Find profile
        p = RoleProfile.query().filter(name=profile_name_or_id).first()
        if not p:
            p = RoleProfile.get(profile_name_or_id)
        if not p:
            raise ValueError(f"Role Profile '{profile_name_or_id}' not found")

        user.role_profile_id = p.id
        user.role_profile_name = p.name
        user.save()

        # Update AuthUser record if exists
        auth_u = AuthUser.query().filter(username=user.username).first()
        if auth_u:
            auth_u.role_profile_name = p.name
            auth_u.save()

        # Link in UserRoleProfile mapping table
        try:
            existing = UserRoleProfile.query().filter(user_id=user.id, profile_id=p.id).first()
            if not existing:
                UserRoleProfile(user_id=user.id, profile_id=p.id).save()
        except Exception as e:
            logger.debug("UserRoleProfile link note: %s", e)

        # Invalidate cache on Redis
        self.cache.invalidate_user(user.username)
        return True

    # ── Dynamic Role Resolution for User ──────────────────────────────────────

    def get_user_roles(self, username_or_id: str) -> Set[str]:
        """Dynamically resolve all Role Names for a user from Role Profile(s) + direct roles.

        Cached on Redis for microsecond lookup.
        """
        target = str(username_or_id).strip().lower()
        cached = self.cache.get_user_roles(target)
        if cached is not None:
            return set(cached)

        roles: Set[str] = set()

        # 1. Resolve User entity
        user = User.query().filter(username=target).first()
        if not user:
            user = User.get(username_or_id)

        profile_names: List[str] = []
        if user:
            if getattr(user, "role_profile_name", None):
                profile_names.append(user.role_profile_name)

            # Check UserRoleProfile mappings
            try:
                urp_list = UserRoleProfile.query().filter(user_id=user.id).all()
                for urp in urp_list:
                    prof = RoleProfile.get(urp.profile_id)
                    if prof and prof.name not in profile_names:
                        profile_names.append(prof.name)
            except Exception:
                pass

            # Direct UserRole assignments
            try:
                direct_roles = UserRole.query().filter(user_id=user.id).all()
                for ur in direct_roles:
                    r_obj = Role.get(ur.role_id)
                    if r_obj and r_obj.is_active:
                        roles.add(r_obj.name.upper())
            except Exception:
                pass

        # Also check AuthUser for profile name
        auth_u = AuthUser.query().filter(username=target).first()
        if auth_u and getattr(auth_u, "role_profile_name", None):
            if auth_u.role_profile_name not in profile_names:
                profile_names.append(auth_u.role_profile_name)

        # 2. Extract collection of Role Names from all assigned Role Profiles
        for prof_name in profile_names:
            prof_data = self.get_role_profile(prof_name)
            if prof_data and prof_data.get("is_active", True):
                for r_name in prof_data.get("role_names", []):
                    roles.add(str(r_name).strip().upper())

        # If user has no roles and no profile, resolve default role profile or default role
        if not roles:
            default_prof = RoleProfile.query().filter(is_default=True).first()
            if default_prof:
                prof_data = self.get_role_profile(default_prof.name)
                if prof_data:
                    for r_name in prof_data.get("role_names", []):
                        roles.add(str(r_name).strip().upper())

        # Traversal of role hierarchy via dynamic_role_protocol
        try:
            from thinkdome.security.rbac.protocol import dynamic_role_protocol
            expanded = dynamic_role_protocol.get_inherited_roles(roles)
            roles.update(expanded)
        except Exception:
            pass

        # Cache on Redis
        self.cache.cache_user_roles(target, roles)
        return roles

    def get_user_role_profile_name(self, username_or_id: str) -> Optional[str]:
        """Return the primary Role Profile name assigned to the user."""
        target = str(username_or_id).strip().lower()
        cached = self.cache.get_user_profile_name(target)
        if cached:
            return cached

        user = User.query().filter(username=target).first()
        if not user:
            user = User.get(username_or_id)
        if user and getattr(user, "role_profile_name", None):
            self.cache.cache_user_profile_name(target, user.role_profile_name)
            return user.role_profile_name

        auth_u = AuthUser.query().filter(username=target).first()
        if auth_u and getattr(auth_u, "role_profile_name", None):
            self.cache.cache_user_profile_name(target, auth_u.role_profile_name)
            return auth_u.role_profile_name

        return None

    # ── Bootstrap & Dynamic Discovery ─────────────────────────────────────────

    def bootstrap_standard_roles_and_profiles(self) -> None:
        """Seed standard low-level roles and role profiles dynamically into the DB."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return

            logger.info("Bootstrapping Dynamic Role Names and Role Profiles into DB & Redis...")

            # ── 1. Register Low-Level Role Names (holding specific low-level privileges) ──
            # Administrative Roles
            self.register_role(
                name="super_admin",
                description="Super administrator with unrestricted platform authority",
                is_admin=True,
                is_system=True,
                doc_perms=[
                    {"document_type": "Workspace", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True, "perm_delete": True},
                    {"document_type": "Sandbox", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True, "perm_delete": True, "perm_access_mcp": True},
                    {"document_type": "NetworkEgress", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True, "perm_delete": True},
                ]
            )
            self.register_role(
                name="system_admin",
                description="Platform system administrator",
                is_admin=True,
                is_system=True,
                parent_role="super_admin",
            )
            self.register_role(
                name="enterprise_admin",
                description="Enterprise organization administrator",
                is_admin=True,
                is_system=True,
                parent_role="system_admin",
            )

            # Functional Low-Level Roles (Granular privileges)
            self.register_role(
                name="sandbox_executor",
                description="Can execute code and manage container sandboxes",
                is_admin=False,
                doc_perms=[
                    {"document_type": "Sandbox", "level": 0, "perm_select": True, "perm_read": True, "perm_create": True, "perm_access_mcp": True},
                ],
            )
            self.register_role(
                name="sandbox_admin",
                description="Full sandbox lifecycle, resource customization, and tenant administration",
                is_admin=True,
                doc_perms=[
                    {"document_type": "Sandbox", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True, "perm_delete": True, "perm_access_mcp": True},
                ],
            )
            self.register_role(
                name="network_egress_manager",
                description="Authorized to establish network egress connections from sandboxes",
                is_admin=False,
                doc_perms=[
                    {"document_type": "NetworkEgress", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True},
                ],
            )
            self.register_role(
                name="console_operator",
                description="Access to interactive console, terminal, and shell execution",
                is_admin=False,
                doc_perms=[
                    {"document_type": "Console", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True},
                ],
            )
            self.register_role(
                name="ide_developer",
                description="Access to IDE editing, workspace editor, and code tools",
                is_admin=False,
                doc_perms=[
                    {"document_type": "IDE", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True},
                ],
            )
            self.register_role(
                name="mcp_orchestrator",
                description="Authorized to discover and invoke MCP tools and orchestrator workflows",
                is_admin=False,
                doc_perms=[
                    {"document_type": "MCPTool", "level": 0, "perm_select": True, "perm_read": True, "perm_access_mcp": True},
                    {"document_type": "Function", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True},
                ],
            )
            self.register_role(
                name="filebox_manager",
                description="Authorized to upload, download, and manage storage artifacts in filebox",
                is_admin=False,
                doc_perms=[
                    {"document_type": "Filebox", "level": 0, "perm_select": True, "perm_read": True, "perm_write": True, "perm_create": True, "perm_delete": True, "perm_file_related": True},
                ],
            )
            self.register_role(
                name="doc_reader",
                description="Read-only access to documentation, metrics, and pages",
                is_admin=False,
                doc_perms=[
                    {"document_type": "Page", "level": 0, "perm_select": True, "perm_read": True},
                    {"document_type": "Sidebar", "level": 0, "perm_select": True, "perm_read": True},
                ],
            )
            self.register_role(
                name="guest_viewer",
                description="Unprivileged guest with minimal public landing view",
                is_admin=False,
                doc_perms=[
                    {"document_type": "Page", "level": 0, "perm_select": True, "perm_read": True},
                ],
            )

            # ── Legacy Aliases Registered in DB so existing configurations work seamlessly ──
            legacy_mappings = [
                ("SUPER_ADMIN", "Full system access", True, "super_admin"),
                ("ADMIN", "Administrator", True, "system_admin"),
                ("ENTERPRISE_ADMIN", "Enterprise Admin", True, "enterprise_admin"),
                ("AGENT_STANDARD", "Standard Agent User", False, None),
                ("ORCH", "Orchestrator Agent", True, None),
                ("ORCHESTRATOR", "Orchestrator Role", True, None),
                ("IDE", "Integrated Development Environment", True, None),
                ("WEB", "Web UI Caller", False, None),
                ("SDK", "SDK Client Caller", False, None),
                ("CURL", "cURL Client Caller", False, None),
                ("DEVELOPER", "Developer Role", False, None),
                ("LLM", "LLM Sandbox Caller", False, None),
                ("GUEST", "Guest Caller", False, "guest_viewer"),
            ]
            for leg_name, leg_desc, leg_admin, leg_parent in legacy_mappings:
                self.register_role(
                    name=leg_name,
                    description=leg_desc,
                    is_admin=leg_admin,
                    parent_role=leg_parent,
                )

            # ── 2. Register Role Profiles (Collections of Role Names) ─────────────
            self.register_role_profile(
                name="Administrator",
                description="Full administration profile bundling all administrative and management role names",
                role_names=[
                    "super_admin", "system_admin", "enterprise_admin", "sandbox_admin",
                    "network_egress_manager", "console_operator", "ide_developer",
                    "mcp_orchestrator", "filebox_manager", "ADMIN", "SUPER_ADMIN",
                ],
                is_default=False,
            )

            self.register_role_profile(
                name="Developer",
                description="Full development profile bundling sandbox execution, console, IDE, MCP, and network egress",
                role_names=[
                    "sandbox_executor", "network_egress_manager", "console_operator",
                    "ide_developer", "mcp_orchestrator", "filebox_manager", "doc_reader",
                    "DEVELOPER", "IDE",
                ],
                is_default=False,
            )

            self.register_role_profile(
                name="Standard Agent",
                description="Default role profile for standard agent execution and tools",
                role_names=[
                    "sandbox_executor", "network_egress_manager", "mcp_orchestrator",
                    "doc_reader", "AGENT_STANDARD", "SDK",
                ],
                is_default=True,
            )

            self.register_role_profile(
                name="Orchestrator",
                description="Role profile for autonomous orchestrator operations",
                role_names=[
                    "sandbox_executor", "network_egress_manager", "mcp_orchestrator",
                    "console_operator", "ORCH", "ORCHESTRATOR",
                ],
                is_default=False,
            )

            self.register_role_profile(
                name="Auditor",
                description="Auditor role profile with read-only inspection capabilities",
                role_names=["doc_reader", "filebox_manager", "AUDITOR"],
                is_default=False,
            )

            self.register_role_profile(
                name="Guest",
                description="Unprivileged guest role profile",
                role_names=["guest_viewer", "GUEST"],
                is_default=False,
            )

            self._initialized = True
            logger.info("✓ RBAC Role Names and Role Profiles successfully bootstrapped and cached.")


# Global singleton
rbac_registry = RoleProfileRegistry.get_instance()
