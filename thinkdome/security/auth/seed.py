"""First-install account and UI data bootstrap.

The UI manifest is data, not Python declarations. Once loaded, UIManager's
database is the only runtime source used by navigation and rendering.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_bootstrap_ui() -> dict:
    path = Path(__file__).resolve().parents[2] / "config" / "ui" / "bootstrap.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("UI bootstrap manifest unavailable: %s", exc)
        return {"workspaces": [], "pages": []}


def seed_superadmin_and_dynamic_ui(site_name: str = "think.local") -> None:
    """Create system accounts, seed standard roles, and seed the initial data manifest once."""
    try:
        from thinkdome.security.rbac.models import User, Role, UserRole, Permission, RolePermission
        from thinkdome.security.rbac.registry import rbac_registry
        from thinkdome.core.ui.models import UIDeveloperConfig
        from thinkdome.core.ui.service import UIManager
        from thinkdome.core.ui.cache import UICacheManager

        # Bootstrap dynamic low-level roles and role profiles into DB & Redis
        rbac_registry.bootstrap_standard_roles_and_profiles()

        # Seed standard roles into rbac_roles so the Workspace Manager
        # can reference them dynamically instead of hardcoding role names.
        _STANDARD_ROLES = [
            ("SUPER_ADMIN", "Full platform access", True),
            ("ADMIN", "Platform administrator", True),
            ("ENTERPRISE_ADMIN", "Enterprise-level administrator", True),
            ("AGENT_STANDARD", "Standard agent user", False),
            ("AUDITOR", "Security auditor with read-only access", False),
            ("FINANCE_MANAGER", "Finance & billing management", False),
            ("GUEST", "Limited guest access", False),
        ]
        for role_name, description, is_system in _STANDARD_ROLES:
            if not Role.query().filter(name=role_name).first():
                Role(name=role_name, description=description, is_active=True, is_system=is_system).save()
                logger.info("Seeded RBAC role: %s", role_name)

        super_role = Role.query().filter(name="SUPER_ADMIN").first()
        wildcard = Permission.query().filter(module="*", resource="*", action="*").first()
        if not wildcard:
            wildcard = Permission(module="*", resource="*", action="*", description="Full workspace administration")
            wildcard.save()
        if not RolePermission.query().filter(role_id=super_role.id, permission_id=wildcard.id).first():
            RolePermission(role_id=super_role.id, permission_id=wildcard.id).save()

        # Initial standard-agent capabilities are ordinary persisted role
        # grants. Workspace administrators can add or remove them at runtime.
        standard_role = Role.query().filter(name="AGENT_STANDARD").first()
        for module, resource, action in (
            ("api", "list_sandboxes", "read"),
            ("api", "sandbox_capacity", "read"),
            ("api", "create_sandbox", "create"),
            ("api", "execute_code", "create"),
            ("api", "execute_batch", "create"),
            ("api", "execute_stream", "create"),
            ("api", "list_tools", "read"),
            ("orchestrator", "run_code", "custom"),
            ("sandbox", "sandbox", "execute"),
            ("sandbox", "sandbox", "read"),
        ):
            grant = Permission.query().filter(module=module, resource=resource, action=action).first()
            if not grant:
                grant = Permission(module=module, resource=resource, action=action, description="Default standard-agent workspace grant")
                grant.save()
            if not RolePermission.query().filter(role_id=standard_role.id, permission_id=grant.id).first():
                RolePermission(role_id=standard_role.id, permission_id=grant.id).save()
        from thinkdome.security.identity.cache import permission_cache
        permission_cache.invalidate_all()

        password_hash = hashlib.sha256(b"admin").hexdigest()
        for username in ("superadmin", "administrator"):
            user = User.query().filter(username=username).first()
            if not user:
                user = User(username=username, email=f"{username}@{site_name}", password_hash=password_hash, status="active")
                user.save()
            if not UserRole.query().filter(user_id=user.id, role_id=super_role.id).first():
                UserRole(user_id=user.id, role_id=super_role.id).save()

        # Reconcile the manifest on every startup so role-policy changes in
        # bootstrap.json reach existing installations, not only fresh sites.
        UIManager().setup(load_bootstrap_ui())
        UICacheManager.get_instance().clear()
        logger.info("System account and dynamic UI bootstrap complete.")
    except Exception as err:
        logger.warning("System bootstrap note: %s", err)

