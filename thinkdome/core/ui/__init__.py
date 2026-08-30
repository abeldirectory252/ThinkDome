"""ThinkDome Dynamic UI Platform Public API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from thinkdome.core.ui.service import UIManager
from thinkdome.core.ui.components import ComponentRegistry
from thinkdome.core.ui.validator import UIValidator

from thinkdome.core.ui.registry import workspace, page, FrameworkUIRegistry

_ui_manager = UIManager()
_ui_registry = FrameworkUIRegistry.get_instance()


class UserPreferencesProxy:
    """Proxy object exposing thinkdome.ui.user_preferences.get() and .save()."""

    def get(self, user_id: str = "default") -> Dict[str, Any]:
        pref = _ui_manager.get_user_preferences(user_id)
        return pref.to_dict() if pref else {}

    def save(self, data: Dict[str, Any], user_id: str = "default") -> Dict[str, Any]:
        return _ui_manager.save_user_preferences(user_id, data)


user_preferences = UserPreferencesProxy()
components = ComponentRegistry.get_instance()


def setup(config: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    return _ui_manager.setup(config)


def create_page(config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.create_page(config)


def update_page(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.update_page(name, config)


def get_page(name: str) -> Optional[Dict[str, Any]]:
    return _ui_manager.get_page(name)


def delete_page(name: str) -> bool:
    return _ui_manager.delete_page(name)


def create_workspace(config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.create_workspace(config)


def update_workspace(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.update_workspace(name, config)


def get_workspace(name: str) -> Optional[Dict[str, Any]]:
    return _ui_manager.get_workspace(name)


def delete_workspace(name: str) -> bool:
    return _ui_manager.delete_workspace(name)


def add_menu_item(workspace: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.add_menu_item(workspace, config)


def update_menu_item(workspace: str, item_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.update_menu_item(workspace, item_name, config)


def remove_menu_item(workspace: str, item_name: str) -> bool:
    return _ui_manager.remove_menu_item(workspace, item_name)


def reorder_menu(workspace: str, item_names: List[str]) -> List[Dict[str, Any]]:
    return _ui_manager.reorder_menu(workspace, item_names)


def validate(config: Dict[str, Any]) -> List[Dict[str, str]]:
    return UIValidator.validate(config)


def get_effective_ui(user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _ui_manager.get_effective_ui(user_context)


def get_navigation(user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _ui_manager.get_effective_ui(user_context)


def save_draft(data: Dict[str, Any], user_id: str = "system") -> Dict[str, Any]:
    return _ui_manager.save_draft(data, user_id)


def get_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    return _ui_manager.get_draft(draft_id)


def preview(draft_id: str, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _ui_manager.preview(draft_id, user_context)


def publish(draft_id: str, user_id: str = "system") -> Dict[str, Any]:
    return _ui_manager.publish(draft_id, user_id)


def list_versions() -> List[Dict[str, Any]]:
    return _ui_manager.list_versions()


def restore_version(version_id: str, user_id: str = "system") -> Dict[str, Any]:
    return _ui_manager.restore_version(version_id, user_id)


def get_tree_view(user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _ui_manager.get_tree_view(user_context)


def get_role_permission_matrix() -> Dict[str, Any]:
    return _ui_manager.get_role_permission_matrix()


def register_entity(config: Dict[str, Any]) -> Dict[str, Any]:
    return _ui_manager.register_entity(config)


def bulk_update_roles(entity_type: str, target_names: List[str], role: str, action: str) -> bool:
    return _ui_manager.bulk_update_roles(entity_type, target_names, role, action)


def get_registry_summary() -> Dict[str, Any]:
    return _ui_manager.get_registry_summary()


__all__ = [
    "workspace",
    "page",
    "setup",
    "create_page",
    "update_page",
    "get_page",
    "delete_page",
    "create_workspace",
    "update_workspace",
    "get_workspace",
    "delete_workspace",
    "add_menu_item",
    "update_menu_item",
    "remove_menu_item",
    "reorder_menu",
    "validate",
    "get_effective_ui",
    "get_navigation",
    "save_draft",
    "get_draft",
    "preview",
    "publish",
    "list_versions",
    "restore_version",
    "get_tree_view",
    "get_role_permission_matrix",
    "register_entity",
    "bulk_update_roles",
    "get_registry_summary",
    "user_preferences",
    "components",
]

