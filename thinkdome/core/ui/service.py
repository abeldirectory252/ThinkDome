"""UI Manager and Core Application Services for ThinkDome Dynamic UI Platform."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from thinkdome.core.ui.models import (
    UIDeveloperConfig,
    UIAdminOverride,
    UIDraft,
    UIVersion,
    UIUserPreference,
)
from thinkdome.core.ui.components import ComponentRegistry
from thinkdome.core.ui.validator import UIValidator
from thinkdome.core.ui.cache import UICacheManager
from thinkdome.core.ui.policy import can_view, normalize_roles


class UIManagerError(Exception):
    """Base exception for UIManager operations."""
    pass


class UIManager:
    """Central orchestration service for ThinkDome Dynamic UI Platform."""

    def __init__(self) -> None:
        self.validator = UIValidator()
        self.components = ComponentRegistry.get_instance()
        self.cache = UICacheManager.get_instance()

    def _hash_config(self, data: Any) -> str:
        """Compute deterministic SHA-256 hash of configuration payload."""
        dumped = json.dumps(data, sort_keys=True)
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

    def _validate_entity_config(self, config: Dict[str, Any], expected_type: Optional[str] = None) -> None:
        """Validate the bounded identity and authorization fields of one UI entity."""
        if not isinstance(config, dict):
            raise UIManagerError("UI entity configuration must be an object")
        name = config.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 255:
            raise UIManagerError("UI entity name must be a non-empty string of at most 255 characters")
        if re.search(r"[\x00-\x1f\x7f]", name):
            raise UIManagerError("UI entity name contains control characters")
        if expected_type and config.get("entity_type", expected_type) != expected_type:
            raise UIManagerError(f"UI entity type must be {expected_type}")
        roles = config.get("allowed_roles", config.get("roles", []))
        if isinstance(roles, str) or not isinstance(roles, (list, tuple, set)):
            raise UIManagerError("allowed_roles must be a list of role names")
        if len(roles) > 100 or any(not isinstance(role, str) or not role.strip() or len(role) > 100 for role in roles):
            raise UIManagerError("allowed_roles contains an invalid or excessive role list")
        try:
            if len(json.dumps(config, ensure_ascii=False)) > 1_000_000:
                raise UIManagerError("UI entity configuration exceeds the 1 MB limit")
        except (TypeError, ValueError) as exc:
            raise UIManagerError("UI entity configuration must contain JSON-compatible values") from exc

    # ──────────────────────────────────────────────────────────────────────────
    # Developer Setup & Synchronization (Idempotent)
    # ──────────────────────────────────────────────────────────────────────────

    def setup(self, config: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
        """Synchronize developer source configuration into developer config store idempotently."""
        errors = self.validator.validate(config)
        if errors:
            raise UIManagerError(f"Configuration validation failed: {errors}")

        result = {
            "workspaces": {"created": 0, "updated": 0, "unchanged": 0},
            "pages": {"created": 0, "updated": 0, "unchanged": 0},
            "items": {"created": 0, "updated": 0, "unchanged": 0},
        }

        # 1. Process Workspaces
        for ws_config in config.get("workspaces", []):
            status = self._sync_entity("workspace", ws_config["name"], ws_config)
            result["workspaces"][status] += 1

            # Sync workspace items
            for item_config in ws_config.get("items", []):
                item_key = f"{ws_config['name']}:{item_config['name']}"
                item_status = self._sync_entity("menu_item", item_key, item_config)
                result["items"][item_status] += 1

        # 2. Process Pages
        for page_config in config.get("pages", []):
            status = self._sync_entity("page", page_config["name"], page_config)
            result["pages"][status] += 1
            self._sync_page_components(page_config)

        self.cache.clear()
        return result

    def _sync_page_components(self, page_config: Dict[str, Any]) -> None:
        """Register every declarative page block as a privilege-bearing UI part."""
        page_name = page_config["name"]
        blocks = page_config.get("blocks", page_config.get("layout", [])) or []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            component_name = block.get("name") or f"{page_name}:block:{index}"
            if UIDeveloperConfig.query().filter(name=f"component:{component_name}").first():
                continue
            component_config = {
                **block,
                "name": component_name,
                "title": block.get("title", block.get("label", f"{page_name} block {index + 1}")),
                "page": page_name,
                "allowed_roles": block.get("allowed_roles", page_config.get("allowed_roles", [])),
            }
            self._sync_entity("component", component_name, component_config)

    def _ensure_page_components_registered(self) -> None:
        """Backfill component registry records for pages created by older versions."""
        for record in UIDeveloperConfig.query().filter(entity_type="page").all():
            self._sync_page_components(record.get_config())

    def _sync_entity(self, entity_type: str, managed_key: str, config: Dict[str, Any]) -> str:
        """Idempotently create or update a single developer entity."""
        from thinkdome.core.orm.orm import _get_active_db, select
        name_id = f"{entity_type}:{managed_key}"
        version_hash = self._hash_config(config)

        db = _get_active_db()
        table = UIDeveloperConfig._table
        stmt = select(table).where(table.c.name == name_id)
        row = db.execute(stmt).first()

        if not row:
            rec = UIDeveloperConfig(
                name=name_id,
                entity_type=entity_type,
                managed_key=managed_key,
                managed_by="thinkdome",
                managed_source="developer_config",
                config_json=json.dumps(config),
                version_hash=version_hash,
            )
            rec.save()
            return "created"

        row_dict = dict(row._mapping)
        rec = UIDeveloperConfig(_loaded=True, **row_dict)

        if row_dict.get("is_deleted"):
            rec._values["is_deleted"] = False
            rec._values["config_json"] = json.dumps(config)
            rec._values["version_hash"] = version_hash
            rec.save()
            return "created"

        if rec.version_hash == version_hash:
            return "unchanged"

        rec.config_json = json.dumps(config)
        rec.version_hash = version_hash
        rec.save()
        return "updated"

    # ──────────────────────────────────────────────────────────────────────────
    # Workspace CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def create_workspace(self, config: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_entity_config(config, "workspace")
        name = config.get("name")
        if not name:
            raise UIManagerError("Workspace name is required")
        self._sync_entity("workspace", name, config)
        self.cache.clear()
        return config

    def update_workspace(self, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        config["name"] = name
        self._validate_entity_config(config, "workspace")
        self._sync_entity("workspace", name, config)
        self.cache.clear()
        return config

    def get_workspace(self, name: str) -> Optional[Dict[str, Any]]:
        rec = UIDeveloperConfig.query().filter(name=f"workspace:{name}").first()
        return rec.get_config() if rec else None

    def get_visible_workspace(self, name: str, user_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Return the compiled workspace for an identity, never raw config."""
        if user_context is None:
            return None
        effective = self.get_effective_ui(user_context)
        return next((item for item in effective.get("workspaces", []) if item.get("name") == name), None)

    def delete_workspace(self, name: str) -> bool:
        rec = UIDeveloperConfig.query().filter(name=f"workspace:{name}").first()
        if rec:
            rec.delete(soft=True)
            self.cache.clear()
            return True
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Page CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def create_page(self, config: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_entity_config(config, "page")
        name = config.get("name")
        if not name:
            raise UIManagerError("Page name is required")
        self._sync_entity("page", name, config)
        self._sync_page_components(config)
        self.cache.clear()
        return config

    def update_page(self, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        config["name"] = name
        self._validate_entity_config(config, "page")
        self._sync_entity("page", name, config)
        self._sync_page_components(config)
        self.cache.clear()
        return config

    def get_page(self, name: str) -> Optional[Dict[str, Any]]:
        rec = UIDeveloperConfig.query().filter(name=f"page:{name}").first()
        return rec.get_config() if rec else None

    def get_visible_page(self, name: str, user_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Return a page only when the supplied identity is allowed to view it."""
        if user_context is None:
            return None
        effective = self.get_effective_ui(user_context)
        return next((item for item in effective.get("pages", []) if item.get("name") == name), None)

    def delete_page(self, name: str) -> bool:
        rec = UIDeveloperConfig.query().filter(name=f"page:{name}").first()
        if rec:
            rec.delete(soft=True)
            for component in UIDeveloperConfig.query().filter(entity_type="component").all():
                if component.get_config().get("page") == name:
                    component.delete(soft=True)
            self.cache.clear()
            return True
        return False

    def delete_component(self, name: str) -> bool:
        rec = UIDeveloperConfig.query().filter(name=f"component:{name}").first()
        if rec:
            rec.delete(soft=True)
            self.cache.clear()
            return True
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Menu Operations
    # ──────────────────────────────────────────────────────────────────────────

    def add_menu_item(self, workspace: str, item_data: Dict[str, Any]) -> Dict[str, Any]:
        ws = self.get_workspace(workspace)
        if not ws:
            raise UIManagerError(f"Workspace '{workspace}' does not exist")

        item_name = item_data.get("name")
        if not item_name:
            raise UIManagerError("Menu item name is required")
        self._validate_entity_config(item_data)

        items = ws.get("items", [])
        if any(i.get("name") == item_name for i in items):
            raise UIManagerError(f"Menu item '{item_name}' already exists in workspace '{workspace}'")

        items.append(item_data)
        ws["items"] = items
        self.update_workspace(workspace, ws)
        return item_data

    def update_menu_item(self, workspace: str, item_name: str, item_data: Dict[str, Any]) -> Dict[str, Any]:
        ws = self.get_workspace(workspace)
        if not ws:
            raise UIManagerError(f"Workspace '{workspace}' does not exist")

        items = ws.get("items", [])
        self._validate_entity_config({**item_data, "name": item_name})
        found = False
        for idx, item in enumerate(items):
            if item.get("name") == item_name:
                item_data["name"] = item_name
                items[idx] = item_data
                found = True
                break

        if not found:
            raise UIManagerError(f"Menu item '{item_name}' not found in workspace '{workspace}'")

        ws["items"] = items
        self.update_workspace(workspace, ws)
        return item_data

    def remove_menu_item(self, workspace: str, item_name: str) -> bool:
        ws = self.get_workspace(workspace)
        if not ws:
            raise UIManagerError(f"Workspace '{workspace}' does not exist")

        items = ws.get("items", [])
        initial_len = len(items)
        ws["items"] = [i for i in items if i.get("name") != item_name]

        if len(ws["items"]) == initial_len:
            return False

        self.update_workspace(workspace, ws)
        return True

    def reorder_menu(self, workspace: str, item_names: List[str]) -> List[Dict[str, Any]]:
        ws = self.get_workspace(workspace)
        if not ws:
            raise UIManagerError(f"Workspace '{workspace}' does not exist")

        items = ws.get("items", [])
        item_map = {i["name"]: i for i in items if "name" in i}

        # Validation: check all item_names belong to workspace
        for name in item_names:
            if name not in item_map:
                raise UIManagerError(f"Item '{name}' does not belong to workspace '{workspace}'")

        reordered = []
        for seq, name in enumerate(item_names, start=10):
            item = item_map[name]
            item["sequence"] = seq
            reordered.append(item)

        # Append any items not explicitly listed at end
        for item in items:
            if item.get("name") not in item_names:
                reordered.append(item)

        ws["items"] = reordered
        self.update_workspace(workspace, ws)
        return reordered

    # ──────────────────────────────────────────────────────────────────────────
    # Effective UI Engine (Developer + Admin + Roles + User Prefs)
    # ──────────────────────────────────────────────────────────────────────────

    def get_effective_ui(self, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Derive Effective UI dynamically across configuration layers."""
        user_id = user_context.get("user_id", "default") if user_context else "default"
        user_roles = normalize_roles(user_context.get("roles", [])) if user_context else None

        # Keep an identified user with no roles distinct from an internal
        # unscoped read. Treating both as ``all`` can reuse an over-broad cache
        # entry and leak role-protected UI.
        role_key = "unscoped" if user_roles is None else ",".join(sorted(user_roles)) or "no-roles"
        cache_key = f"effective:{user_id}:{role_key}"
        cached = self.cache.get(cache_key)
        if cached:
            return copy.deepcopy(cached)

        # 1. Developer Defaults
        dev_configs = UIDeveloperConfig.query().all()
        workspaces_raw: List[Dict[str, Any]] = []
        pages_raw: List[Dict[str, Any]] = []

        for record in dev_configs:
            cfg = record.get_config()
            if record.entity_type == "workspace":
                workspaces_raw.append(cfg)
            elif record.entity_type == "page":
                pages_raw.append(cfg)

        # Sort developer defaults by sequence/name
        workspaces_raw.sort(key=lambda x: (x.get("sequence", 100), x.get("name", "")))
        pages_raw.sort(key=lambda x: (x.get("sequence", 100), x.get("name", "")))

        # 2. Layer Administrator Overrides
        overrides = UIAdminOverride.query().filter(is_active=True).all()
        override_map: Dict[str, Dict[str, Any]] = {}
        for ov in overrides:
            key = f"{ov.target_type}:{ov.target_name}"
            override_map[key] = ov.get_changes()

        workspaces = [self._apply_override("workspace", ws, override_map) for ws in workspaces_raw]
        pages = [self._apply_override("page", page, override_map) for page in pages_raw]

        # 3. Layer Role / Permission Filtering
        if user_roles is not None:
            workspaces = [ws for ws in workspaces if can_view(ws, user_roles)]
            pages = [p for p in pages if can_view(p, user_roles)]
            for ws in workspaces:
                ws["items"] = self._filter_menu_items(ws.get("items", []), user_roles)
            # Component privileges are applied inside already-visible pages.
            # A denied UI part is omitted from the server manifest entirely.
            for page in pages:
                blocks_key = "blocks" if "blocks" in page else "layout"
                blocks = page.get(blocks_key, []) or []
                visible_blocks = []
                for index, block in enumerate(blocks):
                    component_name = block.get("name") if isinstance(block, dict) else None
                    component_name = component_name or f"{page.get('name')}:block:{index}"
                    component = UIDeveloperConfig.query().filter(name=f"component:{component_name}").first()
                    if component and not can_view(component.get_config(), user_roles):
                        continue
                    visible_blocks.append(block)
                page[blocks_key] = visible_blocks

        # 4. Layer User Preferences
        user_pref = self.get_user_preferences(user_id)
        if user_pref:
            favorites = set(user_pref.get_favorites())
            hidden = set(user_pref.get_hidden_items())
            custom_order = user_pref.get_order()

            for ws in workspaces:
                filtered_items = []
                for item in ws.get("items", []):
                    iname = item.get("name", "")
                    if iname in hidden:
                        continue
                    item["is_favorite"] = iname in favorites
                    filtered_items.append(item)

                if custom_order:
                    order_map = {name: idx for idx, name in enumerate(custom_order)}
                    filtered_items.sort(key=lambda x: order_map.get(x.get("name"), 999))

                ws["items"] = filtered_items

        effective = {
            "workspaces": workspaces,
            "pages": pages,
            "user_preferences": user_pref.to_dict() if user_pref else {},
        }

        self.cache.set(cache_key, copy.deepcopy(effective))
        return copy.deepcopy(effective)

    def _apply_override(
        self, target_type: str, entity: Dict[str, Any], override_map: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Apply administrator overrides partially over developer defaults."""
        merged = copy.deepcopy(entity)
        name = merged.get("name")
        key = f"{target_type}:{name}"

        if key in override_map:
            changes = override_map[key]
            for k, v in changes.items():
                merged[k] = v

        # Apply overrides to nested menu items
        if "items" in merged and isinstance(merged["items"], list):
            item_overrides = []
            for item in merged["items"]:
                item_key = f"menu_item:{item.get('name')}"
                scoped_key = f"menu_item:{merged.get('name')}:{item.get('name')}"
                if scoped_key in override_map or item_key in override_map:
                    item_merged = copy.deepcopy(item)
                    changes = override_map.get(scoped_key, override_map.get(item_key, {}))
                    for k, v in changes.items():
                        item_merged[k] = v
                    item_overrides.append(item_merged)
                else:
                    item_overrides.append(item)
            merged["items"] = item_overrides

        return merged

    def _check_roles(self, required_roles: Optional[List[str]], user_roles: set) -> bool:
        """Check if user holds required roles."""
        return can_view({"allowed_roles": required_roles}, user_roles)

    def _filter_menu_items(self, items: Any, user_roles: set) -> List[Dict[str, Any]]:
        """Filter nested menu trees without exposing unauthorized descendants."""
        if not isinstance(items, list):
            return []
        visible = []
        for item in items:
            if not isinstance(item, dict) or not can_view(item, user_roles):
                continue
            item_copy = copy.deepcopy(item)
            if item_copy.get("type") == "group":
                item_copy["items"] = self._filter_menu_items(item_copy.get("items", []), user_roles)
                if not item_copy["items"]:
                    continue
            visible.append(item_copy)
        return visible

    # ──────────────────────────────────────────────────────────────────────────
    # Drafts, Preview & Transactional Publishing
    # ──────────────────────────────────────────────────────────────────────────

    def save_draft(self, data: Dict[str, Any], user_id: str = "system") -> Dict[str, Any]:
        draft_id = data.get("draft_id", str(uuid.uuid4()))
        draft = UIDraft.query().filter(draft_id=draft_id).first()
        if not draft:
            draft = UIDraft(
                draft_id=draft_id,
                title=data.get("title", "Draft UI Configuration"),
                created_by=user_id,
            )

        draft.set_data(data)
        draft.updated_at = str(time.time())
        draft.status = "draft"
        draft.save()
        return draft.to_dict()

    def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        draft = UIDraft.query().filter(draft_id=draft_id).first()
        return draft.to_dict() if draft else None

    def preview(self, draft_or_id: Any, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate non-mutating UI preview of draft changes."""
        if isinstance(draft_or_id, str):
            draft_rec = self.get_draft(draft_or_id)
            if not draft_rec:
                raise UIManagerError(f"Draft '{draft_or_id}' not found")
            draft_data = json.loads(draft_rec.get("data_json", "{}"))
        elif isinstance(draft_or_id, dict):
            draft_data = draft_or_id
        else:
            raise UIManagerError("Invalid draft argument")

        # Temporarily layer draft overrides over effective UI without saving
        current_effective = copy.deepcopy(self.get_effective_ui(user_context))
        draft_overrides = draft_data.get("overrides", [])

        override_map = {f"{o['target_type']}:{o['target_name']}": o.get("changes", {}) for o in draft_overrides}

        for ws in current_effective.get("workspaces", []):
            key = f"workspace:{ws.get('name')}"
            if key in override_map:
                ws.update(override_map[key])

        return current_effective

    def publish(self, draft_id: str, user_id: str = "system") -> Dict[str, Any]:
        """Publish draft overrides transactionally, creating a version and audit entry."""
        draft_rec = UIDraft.query().filter(draft_id=draft_id).first()
        if not draft_rec:
            raise UIManagerError(f"Draft '{draft_id}' not found")

        draft_data = draft_rec.get_data()
        overrides = draft_data.get("overrides", [])

        # Validate draft override targets
        for ov in overrides:
            if "target_type" not in ov or "target_name" not in ov:
                raise UIManagerError(f"Invalid override definition in draft: {ov}")

        # 1. Apply Overrides
        changes_recorded = []
        for ov in overrides:
            ttype = ov["target_type"]
            tname = ov["target_name"]
            changes = ov.get("changes", {})

            rec = UIAdminOverride.query().filter(target_type=ttype, target_name=tname).first()
            if not rec:
                rec = UIAdminOverride(
                    target_type=ttype,
                    target_name=tname,
                    workspace=ov.get("workspace", ""),
                )
            rec.set_changes(changes)
            rec.is_active = True
            rec.save()
            changes_recorded.append({"type": ttype, "name": tname, "action": "updated"})

        # 2. Mark Draft Published
        draft_rec.status = "published"
        draft_rec.save()

        # 3. Create Published Version Record
        existing_versions = UIVersion.query().all()
        next_ver_num = max([v.version_num for v in existing_versions], default=0) + 1
        version_id = f"v{next_ver_num}_{uuid.uuid4().hex[:8]}"

        effective_snapshot = self.get_effective_ui()

        version = UIVersion(
            version_num=next_ver_num,
            version_id=version_id,
            published_by=user_id,
            published_at=str(time.time()),
            changes_json=json.dumps(changes_recorded),
            full_config_json=json.dumps(effective_snapshot),
        )
        version.save()

        # 4. Audit Log Integration
        self._log_audit(
            action="ui.publish",
            target_type="ui_config",
            target_name="global",
            actor=user_id,
            details={"draft_id": draft_id, "version_id": version_id, "changes_count": len(changes_recorded)},
        )

        # 5. Clear Caches
        self.cache.clear()
        return effective_snapshot

    # ──────────────────────────────────────────────────────────────────────────
    # Versioning & Restoration
    # ──────────────────────────────────────────────────────────────────────────

    def list_versions(self) -> List[Dict[str, Any]]:
        versions = UIVersion.query().all()
        versions.sort(key=lambda v: v.version_num, reverse=True)
        return [v.to_dict() for v in versions]

    def restore_version(self, version_id: str, user_id: str = "system") -> Dict[str, Any]:
        target_version = UIVersion.query().filter(version_id=version_id).first()
        if not target_version:
            raise UIManagerError(f"Version '{version_id}' not found")

        full_config = target_version.get_full_config()

        # Clear active overrides and restore snapshot state
        for ov in UIAdminOverride.query().all():
            ov.is_active = False
            ov.save()

        self._log_audit(
            action="ui.restore",
            target_type="ui_version",
            target_name=version_id,
            actor=user_id,
            details={"restored_version": version_id},
        )

        self.cache.clear()
        return full_config

    # ──────────────────────────────────────────────────────────────────────────
    # User Preferences
    # ──────────────────────────────────────────────────────────────────────────

    def get_user_preferences(self, user_id: str) -> Optional[UIUserPreference]:
        return UIUserPreference.query().filter(user_id=user_id).first()

    def save_user_preferences(self, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        pref = self.get_user_preferences(user_id)
        if not pref:
            pref = UIUserPreference(user_id=user_id)

        if "default_workspace" in data:
            pref.default_workspace = data["default_workspace"]
        if "favorites" in data:
            pref.set_favorites(data["favorites"])
        if "hidden_items" in data:
            pref.set_hidden_items(data["hidden_items"])
        if "order" in data:
            pref.set_order(data["order"])

        pref.save()
        self.cache.clear(f"effective:{user_id}")
        return pref.to_dict()

    # ──────────────────────────────────────────────────────────────────────────
    # Audit Trail Helper
    # ──────────────────────────────────────────────────────────────────────────

    def _log_audit(
        self, action: str, target_type: str, target_name: str, actor: str, details: Dict[str, Any]
    ) -> None:
        """Integrate with ThinkDome RBAC Audit System."""
        try:
            from thinkdome.security.rbac.models import RbacAuditLog
            log_entry = RbacAuditLog(
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_name,
                details=json.dumps(details),
                ip_address="127.0.0.1",
            )
            log_entry.save()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Framework Registry & Tree View Services
    # ──────────────────────────────────────────────────────────────────────────

    def get_tree_view(self, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return hierarchical tree view of workspaces, pages, and components."""
        self._ensure_page_components_registered()
        effective = self.get_effective_ui(user_context)
        tree = []

        for ws in effective.get("workspaces", []):
            ws_node = {
                "id": f"ws:{ws.get('name')}",
                "name": ws.get("name"),
                "label": ws.get("label", ws.get("name")),
                "type": "workspace",
                "icon": ws.get("icon", "▦"),
                "roles": ws.get("allowed_roles", []),
                "children": []
            }
            # Workspace menu items
            items = ws.get("items", [])
            for item in items:
                ws_node["children"].append({
                    "id": f"item:{ws.get('name')}:{item.get('name')}",
                    "name": item.get("name"),
                    "label": item.get("label", item.get("name")),
                    "type": "menu_item",
                    "route": item.get("route", ""),
                    "icon": item.get("icon", "link"),
                    "roles": item.get("allowed_roles", []),
                    "children": []
                })
            tree.append(ws_node)

        # Pages tree
        pages_tree = []
        for p in effective.get("pages", []):
            p_node = {
                "id": f"page:{p.get('name')}",
                "name": p.get("name"),
                "label": p.get("title", p.get("name")),
                "type": "page",
                "icon": "file-text",
                "roles": p.get("allowed_roles", []),
                "children": []
            }
            for idx, comp in enumerate(p.get("layout", p.get("blocks", []))):
                p_node["children"].append({
                    "id": f"comp:{p.get('name')}:{idx}",
                    "name": comp.get("title", comp.get("label", f"Component #{idx+1}")),
                    "label": comp.get("title", comp.get("text", comp.get("label", comp.get("type")))),
                    "type": comp.get("type", "component"),
                    "details": comp,
                    "children": []
                })
            pages_tree.append(p_node)

        ui_parts_tree = []
        for rec in UIDeveloperConfig.query().filter(entity_type="component").all():
            cfg = rec.get_config()
            ui_parts_tree.append({
                "id": f"component:{rec.managed_key}",
                "name": cfg.get("name", rec.managed_key),
                "label": cfg.get("title", cfg.get("label", rec.managed_key)),
                "type": "component",
                "roles": cfg.get("allowed_roles", []),
                "children": []
            })

        return {
            "workspaces": tree,
            "pages": pages_tree,
            "ui_parts": ui_parts_tree,
        }

    def get_role_permission_matrix(self) -> Dict[str, Any]:
        """Return cross-cutting matrix of Pages/Modules/Processes mapped to roles."""
        self._ensure_page_components_registered()
        from thinkdome.security.rbac.models import Role
        roles_list = [r.name for r in Role.query().all()]
        if not roles_list:
            roles_list = ["SUPER_ADMIN", "ADMIN", "ENTERPRISE_ADMIN", "AGENT_STANDARD", "GUEST"]

        dev_configs = UIDeveloperConfig.query().all()
        pages_matrix = []
        modules_matrix = []
        processes_matrix = []
        components_matrix = []

        for rec in dev_configs:
            cfg = rec.get_config()
            roles_allowed = normalize_roles(cfg.get("allowed_roles", []))
            item_entry = {
                "name": cfg.get("name", rec.managed_key),
                "title": cfg.get("title", cfg.get("label", rec.managed_key)),
                "entity_type": rec.entity_type,
                "allowed_roles": sorted(roles_allowed),
                "role_access": {role: (not roles_allowed or bool(normalize_roles([role]).intersection(roles_allowed))) for role in roles_list}
            }
            if rec.entity_type == "page":
                pages_matrix.append(item_entry)
            elif rec.entity_type == "workspace":
                modules_matrix.append(item_entry)
            elif rec.entity_type == "component":
                components_matrix.append(item_entry)

        # Standard Process Privileges catalog
        processes = [
            {"name": "sandbox_create", "title": "Create Sandboxes", "category": "process", "allowed_roles": ["SUPER_ADMIN", "ADMIN", "AGENT_STANDARD"]},
            {"name": "sandbox_execute", "title": "Execute Code & Commands", "category": "process", "allowed_roles": ["SUPER_ADMIN", "ADMIN", "AGENT_STANDARD"]},
            {"name": "network_egress_manage", "title": "Manage Egress Rules", "category": "process", "allowed_roles": ["SUPER_ADMIN", "ENTERPRISE_ADMIN"]},
            {"name": "ui_customizer_publish", "title": "Publish UI Customizations", "category": "process", "allowed_roles": ["SUPER_ADMIN", "ADMIN"]},
            {"name": "user_role_assign", "title": "Assign User Roles", "category": "process", "allowed_roles": ["SUPER_ADMIN"]},
        ]
        for proc in processes:
            roles_allowed = normalize_roles(proc["allowed_roles"])
            processes_matrix.append({
                "name": proc["name"],
                "title": proc["title"],
                "entity_type": "process",
                "allowed_roles": sorted(roles_allowed),
                "role_access": {role: (not roles_allowed or bool(normalize_roles([role]).intersection(roles_allowed))) for role in roles_list}
            })

        return {
            "roles": roles_list,
            "pages": pages_matrix,
            "modules": modules_matrix,
            "processes": processes_matrix,
            "ui_parts": components_matrix,
        }

    def register_entity(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """The Boss: Register any workspace, page, component, or menu item here first."""
        if not isinstance(config, dict):
            raise UIManagerError("Entity registration payload must be an object")
        entity_type = config.get("entity_type", "page")
        if entity_type not in {"workspace", "page", "component", "menu_item", "mcp_tool"}:
            raise UIManagerError(f"Unsupported UI entity type: {entity_type}")
        self._validate_entity_config(config, entity_type if entity_type in {"workspace", "page"} else None)
        name = config.get("name")
        if not name:
            raise UIManagerError("Entity name is required for registration.")

        if entity_type == "workspace":
            return self.create_workspace(config)
        elif entity_type == "page":
            return self.create_page(config)
        elif entity_type == "menu_item":
            ws_name = config.get("workspace")
            if not ws_name:
                raise UIManagerError("Workspace name required for menu_item registration.")
            return self.add_menu_item(ws_name, config)
        else:
            # Custom component / block registration
            key = f"component:{name}"
            rec = UIDeveloperConfig.query().filter(name=key).first()
            if not rec:
                rec = UIDeveloperConfig(
                    name=key,
                    entity_type="component",
                    managed_key=name,
                    managed_by="system",
                    managed_source="registry_boss",
                    config_json=json.dumps(config),
                    version_hash=self._hash_config(config)
                )
            else:
                rec.config_json = json.dumps(config)
                rec.version_hash = self._hash_config(config)
            rec.save()
            self.cache.clear()
            return config

    def register_mcp_tool(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Persist administrator-owned MCP metadata and visibility policy."""
        self._validate_entity_config(config)
        name = config["name"]
        normalized = {
            **config,
            "entity_type": "mcp_tool",
            "title": config.get("title") or config.get("label") or name,
            "description": config.get("description", ""),
            "is_active": bool(config.get("is_active", True)),
            "deleted": False,
            "allowed_roles": list(config.get("allowed_roles", [])),
        }
        self._sync_entity("mcp_tool", name, normalized)
        self.cache.clear()
        return normalized

    def delete_mcp_tool(self, name: str) -> bool:
        rec = UIDeveloperConfig.query().filter(name=f"mcp_tool:{name}").first()
        if rec:
            # Keep a deny tombstone. Removing the record would make the
            # runtime default active again and could silently re-enable a
            # previously disabled tool.
            config = rec.get_config()
            config["is_active"] = False
            config["deleted"] = True
            rec.set_config(config)
            rec.version_hash = self._hash_config(config)
            rec.save()
            self.cache.clear()
            return True
        return False

    def get_mcp_tool_metadata(self) -> Dict[str, Dict[str, Any]]:
        records = UIDeveloperConfig.query().filter(entity_type="mcp_tool").all()
        return {record.managed_key: record.get_config() for record in records}

    def bulk_update_roles(self, entity_type: str, target_names: List[str], role: str, action: str) -> bool:
        """Grant or deny a role across multiple target entities."""
        valid_types = {"page", "workspace", "process", "component", "permission"}
        if entity_type not in valid_types:
            raise UIManagerError(f"Unsupported UI privilege entity type: {entity_type}")
        if action not in {"grant", "deny"}:
            raise UIManagerError("Privilege action must be grant or deny")
        if not isinstance(role, str) or not role.strip() or len(role) > 100:
            raise UIManagerError("A valid target role is required")
        if not isinstance(target_names, list) or not target_names or len(target_names) > 100:
            raise UIManagerError("Provide between 1 and 100 privilege targets")
        if any(not isinstance(name, str) or not name.strip() or len(name) > 255 for name in target_names):
            raise UIManagerError("Privilege targets must be non-empty names")
        for name in target_names:
            key = f"{entity_type}:{name}"
            rec = UIDeveloperConfig.query().filter(name=key).first()
            if rec:
                cfg = rec.get_config()
                roles = set(cfg.get("allowed_roles", []))
                if action == "grant":
                    roles.add(role)
                elif action == "deny":
                    roles.discard(role)
                cfg["allowed_roles"] = list(roles)
                rec.set_config(cfg)
                rec.version_hash = self._hash_config(cfg)
                rec.save()
        self.cache.clear()
        return True

    def get_registry_summary(self) -> Dict[str, Any]:
        """Return central registry of all registered UI parts, whitelists, and version info."""
        configs = UIDeveloperConfig.query().all()
        items = []
        for c in configs:
            cfg = c.get_config()
            items.append({
                "id": c.name,
                "entity_type": c.entity_type,
                "managed_key": c.managed_key,
                "managed_by": c.managed_by,
                "managed_source": c.managed_source,
                "title": cfg.get("title", cfg.get("label", c.managed_key)),
                "allowed_roles": cfg.get("allowed_roles", []),
                "version_hash": c.version_hash[:8] if c.version_hash else "v1.0",
                "config": cfg
            })
        versions = self.list_versions()
        return {
            "registered_items": items,
            "total_registered": len(items),
            "versions": versions,
            "registered_components": list(self.components._renderers.keys())
        }
