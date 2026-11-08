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


def allocate_privilege(document_type: str, role: str, permissions: Any, level: int = 0, user_id: Optional[str] = None, workspace_id: Optional[str] = None, is_denial: bool = False) -> Dict[str, Any]:
    return _ui_manager.allocate_privilege(document_type, role, permissions, level=level, user_id=user_id, workspace_id=workspace_id, is_denial=is_denial)


def grant_privilege(document_type: str, role: str, permissions: Any, level: int = 0, user_id: Optional[str] = None) -> Dict[str, Any]:
    return _ui_manager.grant_privilege(document_type, role, permissions, level=level, user_id=user_id)


def deny_privilege(document_type: str, role: str, permissions: Any, level: int = 0, user_id: Optional[str] = None) -> Dict[str, Any]:
    return _ui_manager.deny_privilege(document_type, role, permissions, level=level, user_id=user_id)


def customize_exemption(target_name_or_doc_type: str, exempt: bool = True) -> bool:
    return _ui_manager.customize_exemption(target_name_or_doc_type, exempt=exempt)


def override_privilege(workspace_id: str, document_type: str, role: str, permissions: Any, is_denial: bool = False, is_custom_exempt: bool = False, level: int = 0, user_id: Optional[str] = None, actor: str = "workspace_manager") -> Dict[str, Any]:
    return _ui_manager.override_privilege(workspace_id, document_type, role, permissions, is_denial=is_denial, is_custom_exempt=is_custom_exempt, level=level, user_id=user_id, actor=actor)


def bulk_override_privileges(workspace_id: str, overrides: List[Dict[str, Any]], actor: str = "workspace_manager") -> List[Dict[str, Any]]:
    return _ui_manager.bulk_override_privileges(workspace_id, overrides, actor=actor)


def reset_privileges_to_defaults(workspace_id: str, document_type: Optional[str] = None, actor: str = "workspace_manager") -> int:
    return _ui_manager.reset_privileges_to_defaults(workspace_id, document_type=document_type, actor=actor)


def get_privilege_overrides(workspace_id: str) -> List[Dict[str, Any]]:
    return _ui_manager.get_privilege_overrides(workspace_id)


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
    "allocate_privilege",
    "grant_privilege",
    "deny_privilege",
    "customize_exemption",
    "override_privilege",
    "bulk_override_privileges",
    "reset_privileges_to_defaults",
    "get_privilege_overrides",
    "user_preferences",
    "components",
]

