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
    """Create system accounts and seed the initial data manifest once."""
    try:
        from thinkdome.security.rbac.models import User, Role, UserRole
        from thinkdome.core.ui.models import UIDeveloperConfig
        from thinkdome.core.ui.service import UIManager
        from thinkdome.core.ui.cache import UICacheManager

        super_role = Role.query().filter(name="SUPER_ADMIN").first()
        if not super_role:
            super_role = Role(name="SUPER_ADMIN", description="Full platform access", is_active=True, is_system=True)
            super_role.save()

        password_hash = hashlib.sha256(b"admin").hexdigest()
        for username in ("superadmin", "administrator"):
            user = User.query().filter(username=username).first()
            if not user:
                user = User(username=username, email=f"{username}@{site_name}", password_hash=password_hash, status="active")
                user.save()
            if not UserRole.query().filter(user_id=user.id, role_id=super_role.id).first():
                UserRole(user_id=user.id, role_id=super_role.id).save()

        if not UIDeveloperConfig.query().all():
            UIManager().setup(load_bootstrap_ui())
        UICacheManager.get_instance().clear()
        logger.info("System account and dynamic UI bootstrap complete.")
    except Exception as err:
        logger.warning("System bootstrap note: %s", err)
