"""ThinkDome Custom ORM Models for Dynamic UI Platform."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    BooleanField,
    TextField,
    SelectField,
)


class UIDeveloperConfig(Model):
    """Stores developer-defined default UI state and ownership metadata."""
    __tablename__ = "ui_developer_configs"

    # Unique identifier key, e.g., "page:page_a", "workspace:workspace_a"
    name = StringField(required=True, indexed=True, unique=True)
    entity_type = SelectField(choices=["workspace", "page", "component", "menu_item"], required=True)
    managed_key = StringField(required=True, indexed=True)
    managed_by = StringField(default="thinkdome")
    managed_source = StringField(default="developer_config")
    config_json = TextField(default="{}")
    version_hash = StringField(default="")

    def get_config(self) -> Dict[str, Any]:
        """Parse stored JSON payload."""
        try:
            return json.loads(self.config_json or "{}")
        except Exception:
            return {}

    def set_config(self, data: Dict[str, Any]) -> None:
        """Store dictionary payload as JSON string."""
        self.config_json = json.dumps(data)


class UIAdminOverride(Model):
    """Stores visual administrator overrides separate from developer defaults."""
    __tablename__ = "ui_admin_overrides"

    # Target entity type: "workspace", "page", "menu_item", "component"
    target_type = SelectField(choices=["workspace", "page", "menu_item", "component"], required=True)
    target_name = StringField(required=True, indexed=True)
    workspace = StringField(default="", indexed=True)  # Parent workspace if target is menu item
    changes_json = TextField(default="{}")
    is_active = BooleanField(default=True)

    def get_changes(self) -> Dict[str, Any]:
        """Parse stored override dictionary."""
        try:
            return json.loads(self.changes_json or "{}")
        except Exception:
            return {}

    def set_changes(self, data: Dict[str, Any]) -> None:
        """Store override dictionary as JSON string."""
        self.changes_json = json.dumps(data)


class UIDraft(Model):
    """Stores unpublished administrator draft states for UI Builder."""
    __tablename__ = "ui_drafts"

    draft_id = StringField(required=True, indexed=True, unique=True)
    title = StringField(default="Draft UI Configuration")
    data_json = TextField(default="{}")
    status = SelectField(choices=["draft", "published", "discarded"], default="draft")
    created_by = StringField(default="system")
    updated_at = StringField(default="")

    def get_data(self) -> Dict[str, Any]:
        """Parse stored draft payload."""
        try:
            return json.loads(self.data_json or "{}")
        except Exception:
            return {}

    def set_data(self, data: Dict[str, Any]) -> None:
        """Store draft payload as JSON string."""
        self.data_json = json.dumps(data)


class UIVersion(Model):
    """Immutable historical version records created upon publishing UI overrides."""
    __tablename__ = "ui_versions"

    version_num = IntegerField(required=True, indexed=True)
    version_id = StringField(required=True, indexed=True, unique=True)
    published_by = StringField(default="system")
    published_at = StringField(default="")
    changes_json = TextField(default="[]")
    full_config_json = TextField(default="{}")

    def get_changes(self) -> List[Dict[str, Any]]:
        """Parse list of recorded changes."""
        try:
            return json.loads(self.changes_json or "[]")
        except Exception:
            return []

    def get_full_config(self) -> Dict[str, Any]:
        """Parse full UI configuration snapshot."""
        try:
            return json.loads(self.full_config_json or "{}")
        except Exception:
            return {}


class UIUserPreference(Model):
    """Individual per-user personalizations isolated from global configuration."""
    __tablename__ = "ui_user_preferences"

    user_id = StringField(required=True, indexed=True, unique=True)
    default_workspace = StringField(default="")
    favorites_json = TextField(default="[]")
    hidden_items_json = TextField(default="[]")
    order_json = TextField(default="[]")

    def get_favorites(self) -> List[str]:
        try:
            return json.loads(self.favorites_json or "[]")
        except Exception:
            return []

    def set_favorites(self, items: List[str]) -> None:
        self.favorites_json = json.dumps(items)

    def get_hidden_items(self) -> List[str]:
        try:
            return json.loads(self.hidden_items_json or "[]")
        except Exception:
            return []

    def set_hidden_items(self, items: List[str]) -> None:
        self.hidden_items_json = json.dumps(items)

    def get_order(self) -> List[str]:
        try:
            return json.loads(self.order_json or "[]")
        except Exception:
            return []

    def set_order(self, items: List[str]) -> None:
        self.order_json = json.dumps(items)


def initialize_ui_schema() -> None:
    """Ensure all Dynamic UI Platform tables exist in the current site database."""
    try:
        from thinkdome.core.orm.orm import Base, _get_active_db
        db = _get_active_db()
        Base.metadata.create_all(db.bind if hasattr(db, "bind") else db.engine if hasattr(db, "engine") else None, checkfirst=True)
    except Exception as e:
        pass

