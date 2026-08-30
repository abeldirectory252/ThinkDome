"""ThinkDome Dynamic UI Platform — Whitelisted API Methods.

These are the server-side methods exposed through the ThinkDome RPC
framework via @thinkdome.whitelist(). Frontend calls them as:

    await thinkdome.call("thinkdome.core.ui.api.get_navigation")
    await thinkdome.call("thinkdome.core.ui.api.setup_dynamic_ui", config={...})

Each method enforces permissions server-side — the frontend never
controls authorization.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import thinkdome
from thinkdome.core.ui.service import UIManager, UIManagerError
from thinkdome.core.ui.validator import UIValidator
from thinkdome.core.ui.components import ComponentRegistry


def _get_manager() -> UIManager:
    return UIManager()


def _get_user_from_session(session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract user context from session or return default."""
    if not session:
        session = thinkdome.get_session() or {}
    role = session.get("role", "GUEST")
    roles = session.get("roles") or ([role] if role else [])
    return {
        "user_id": session.get("username", session.get("user_id", "system")),
        "roles": roles,
        "role": role,
    }


# ── Setup ─────────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def setup_dynamic_ui(config, session=None):
    """Idempotently synchronize developer UI configuration.

    This is the primary entry point for declarative UI setup::

        THINKDOME_UI = {
            "workspaces": [...],
            "pages": [...],
        }

        @thinkdome.whitelist()
        def setup():
            return thinkdome.call(
                "thinkdome.core.ui.api.setup_dynamic_ui",
                config=THINKDOME_UI,
            )
    """
    mgr = _get_manager()
    return mgr.setup(config)


# ── Navigation & Effective UI ─────────────────────────────────────────────────

@thinkdome.whitelist(allow_guest=True)
def get_navigation(session=None):
    """Return the effective UI for the current authenticated user.

    Layers: Developer Defaults → Admin Overrides → Permissions → User Prefs.
    """
    mgr = _get_manager()
    user_ctx = _get_user_from_session(session)
    return mgr.get_effective_ui(user_ctx)


@thinkdome.whitelist(allow_guest=True)
def get_effective_ui(session=None):
    """Alias for get_navigation."""
    return get_navigation(session=session)


# ── UI Builder ────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def get_ui_builder(session=None):
    """Return the full builder state: effective UI, available components, versions.

    This powers the visual UI Builder interface.
    """
    mgr = _get_manager()
    user_ctx = _get_user_from_session(session)

    effective = mgr.get_effective_ui(user_ctx)
    versions = mgr.list_versions()
    registry = ComponentRegistry.get_instance()

    return {
        "effective": effective,
        "versions": versions,
        "components": list(registry._renderers.keys()),
    }


# ── Workspace CRUD ────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def create_workspace(config, session=None):
    """Create a new workspace."""
    return _get_manager().create_workspace(config)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def update_workspace(name, config, session=None):
    """Update an existing workspace configuration."""
    return _get_manager().update_workspace(name, config)


@thinkdome.whitelist(allow_guest=True)
def get_workspace(name, session=None):
    """Retrieve a workspace by name."""
    return _get_manager().get_visible_workspace(name, _get_user_from_session(session))


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def delete_workspace(name, session=None):
    """Delete a workspace."""
    return _get_manager().delete_workspace(name)


# ── Page CRUD ─────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def create_page(config, session=None):
    """Create a new page."""
    return _get_manager().create_page(config)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def update_page(name, config, session=None):
    """Update an existing page."""
    return _get_manager().update_page(name, config)


@thinkdome.whitelist(allow_guest=True)
def get_page(name, session=None):
    """Retrieve a page by name."""
    return _get_manager().get_visible_page(name, _get_user_from_session(session))


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def delete_page(name, session=None):
    """Delete a page."""
    return _get_manager().delete_page(name)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def delete_component(name, session=None):
    """Delete a registered UI component from the central registry."""
    return _get_manager().delete_component(name)


# ── Menu Operations ──────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def add_menu_item(workspace, data, session=None):
    """Add a menu item to a workspace."""
    return _get_manager().add_menu_item(workspace, data)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def update_menu_item(workspace, item_name, data, session=None):
    """Update a menu item within a workspace."""
    return _get_manager().update_menu_item(workspace, item_name, data)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def remove_menu_item(workspace, item_name, session=None):
    """Remove a menu item from a workspace."""
    return _get_manager().remove_menu_item(workspace, item_name)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def reorder_menu(workspace, items, session=None):
    """Reorder menu items in a workspace.

    ``items`` is a list of item names in the desired order.
    """
    return _get_manager().reorder_menu(workspace, items)


# ── Validation ────────────────────────────────────────────────────────────────

@thinkdome.whitelist(allow_guest=True)
def validate_config(config, session=None):
    """Validate a UI configuration and return structured errors."""
    return UIValidator.validate(config)


# ── Drafts ────────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def save_ui_draft(data, session=None):
    """Save an administrator UI draft."""
    user = _get_user_from_session(session)
    return _get_manager().save_draft(data, user_id=user["user_id"])


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def get_draft(draft_id, session=None):
    """Retrieve a saved draft by ID."""
    return _get_manager().get_draft(draft_id)


# ── Preview ───────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def preview_ui(draft_id, session=None):
    """Preview what the UI would look like after applying a draft.

    This does NOT mutate the published configuration.
    """
    user_ctx = _get_user_from_session(session)
    return _get_manager().preview(draft_id, user_ctx)


# ── Publish ───────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def publish_ui(draft_id, session=None):
    """Publish a draft's overrides into the live UI configuration.

    This creates a version record and audit entry.
    """
    user = _get_user_from_session(session)
    return _get_manager().publish(draft_id, user_id=user["user_id"])


# ── Versioning ────────────────────────────────────────────────────────────────

@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def list_versions(session=None):
    """List all published UI versions."""
    return _get_manager().list_versions()


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def restore_version(version_id, session=None):
    """Restore a previously published UI version."""
    user = _get_user_from_session(session)
    return _get_manager().restore_version(version_id, user_id=user["user_id"])


# ── User Preferences ─────────────────────────────────────────────────────────

@thinkdome.whitelist(allow_guest=False)
def get_user_preferences(session=None):
    """Get the current user's UI preferences."""
    user = _get_user_from_session(session)
    pref = _get_manager().get_user_preferences(user["user_id"])
    return pref.to_dict() if pref else {}


@thinkdome.whitelist(allow_guest=False)
def save_user_preferences(data, session=None):
    """Save the current user's UI preferences."""
    user = _get_user_from_session(session)
    return _get_manager().save_user_preferences(user["user_id"], data)


# ── Introspection ─────────────────────────────────────────────────────────────

@thinkdome.whitelist(allow_guest=True)
def get_platform_summary(session=None):
    """Return introspection summary of currently configured platform state."""
    mgr = _get_manager()
    user_ctx = _get_user_from_session(session)
    effective = mgr.get_effective_ui(user_ctx)
    versions = mgr.list_versions()
    return {
        "workspaces": effective.get("workspaces", []),
        "pages": effective.get("pages", []),
        "versions": versions,
        "active_version": versions[0]["version_id"] if versions else "v1.0",
        "total_workspaces": len(effective.get("workspaces", [])),
        "total_pages": len(effective.get("pages", [])),
    }


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN"])
def list_methods(session=None):
    """List all registered whitelisted methods and their metadata."""
    from thinkdome.core.handler import get_all_whitelisted_methods
    return get_all_whitelisted_methods()


@thinkdome.whitelist(allow_guest=True)
def get_tree_view(session=None):
    """Return tree structure of workspaces, pages, and components for viewer."""
    mgr = _get_manager()
    user_ctx = _get_user_from_session(session)
    return mgr.get_tree_view(user_ctx)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def get_role_permission_matrix(session=None):
    """Return privilege mapping matrix for pages, modules, and processes."""
    mgr = _get_manager()
    return mgr.get_role_permission_matrix()


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def register_entity(config, session=None):
    """The Boss: Register any workspace, page, component, or menu item."""
    mgr = _get_manager()
    return mgr.register_entity(config)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def bulk_update_roles(entity_type, target_names, role, action, session=None):
    """Bulk update role privileges for given targets."""
    mgr = _get_manager()
    return mgr.bulk_update_roles(entity_type, target_names, role, action)


@thinkdome.whitelist(roles=["ADMIN", "SUPER_ADMIN", "ENTERPRISE_ADMIN"])
def get_registry_summary(session=None):
    """Return full UI framework registry summary."""
    mgr = _get_manager()
    return mgr.get_registry_summary()
