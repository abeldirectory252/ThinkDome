"""Comprehensive Automated Test Suite for ThinkDome Dynamic UI Platform."""

from __future__ import annotations

import os
import pytest
import thinkdome
import thinkdome.core.ui as ui
from thinkdome.core.ui.service import UIManager, UIManagerError
from thinkdome.core.ui.components import ComponentRegistry, ComponentRenderError, BaseComponentRenderer
from thinkdome.core.ui.cache import UICacheManager
from thinkdome.security.rbac.models import RbacAuditLog


@pytest.fixture(autouse=True)
def setup_kernel_and_db():
    """Ensure clean Kernel and database environment for each test."""
    os.environ["THINKDOME_SITE"] = "think.local"
    from thinkdome.core.kernel.kernel import Kernel
    from thinkdome.core.ui.models import UIDeveloperConfig, UIAdminOverride, UIDraft, UIVersion, UIUserPreference
    kernel = Kernel.current()
    kernel.initialize()

    # Clean UI tables between test runs
    for model in (UIDeveloperConfig, UIAdminOverride, UIDraft, UIVersion, UIUserPreference):
        for rec in model.query().all():
            rec.delete(soft=False)
    UICacheManager.get_instance().clear()
    yield


# ── 1. Configuration & Validation Tests ──────────────────────────────────────

def test_valid_configuration_validation():
    valid_cfg = {
        "workspaces": [
            {
                "name": "ws_test",
                "label": "Workspace Test",
                "items": [
                    {"name": "item_1", "type": "page", "label": "Item 1", "route": "page-1"}
                ]
            }
        ],
        "pages": [
            {
                "name": "page_test",
                "title": "Page Test",
                "route": "page-test",
                "layout": [
                    {"type": "heading", "text": "Hello World", "level": 1}
                ]
            }
        ]
    }
    errors = ui.validate(valid_cfg)
    assert errors == []


def test_invalid_configuration_validation():
    invalid_cfg = {
        "workspaces": [
            {"name": "ws_1"},  # Missing label
            {"name": "ws_1", "label": "Duplicate WS"},  # Duplicate name
        ],
        "pages": [
            {"name": "page_1", "title": "Page 1"},  # Missing route
            {"name": "page_2", "title": "Page 2", "route": "p2", "layout": [{"type": "nonexistent_component"}]}
        ]
    }
    errors = ui.validate(invalid_cfg)
    assert len(errors) > 0
    err_paths = [e["path"] for e in errors]
    assert "workspaces[0].label" in err_paths
    assert "workspaces[1].name" in err_paths
    assert "pages[0].route" in err_paths
    assert "pages[1].layout[0].type" in err_paths


# ── 2. Idempotency & Setup Tests ──────────────────────────────────────────────

def test_setup_100x_idempotency():
    sample_ui = {
        "workspaces": [
            {
                "name": "workspace_idempotent",
                "label": "Idempotent Workspace",
                "sequence": 10,
                "items": [
                    {"name": "item_a", "type": "page", "label": "Item A", "route": "page-a"}
                ]
            }
        ],
        "pages": [
            {
                "name": "page_idempotent",
                "title": "Idempotent Page",
                "route": "page-idem",
                "layout": [{"type": "heading", "text": "Test Heading", "level": 1}]
            }
        ]
    }

    # 1st Execution -> created
    res1 = ui.setup(sample_ui)
    assert res1["workspaces"]["created"] == 1
    assert res1["pages"]["created"] == 1
    assert res1["items"]["created"] == 1

    # 2nd to 100th Executions -> all unchanged
    for _ in range(99):
        res_n = ui.setup(sample_ui)
        assert res_n["workspaces"]["created"] == 0
        assert res_n["workspaces"]["updated"] == 0
        assert res_n["workspaces"]["unchanged"] == 1
        assert res_n["pages"]["created"] == 0
        assert res_n["pages"]["updated"] == 0
        assert res_n["pages"]["unchanged"] == 1
        assert res_n["items"]["created"] == 0
        assert res_n["items"]["updated"] == 0
        assert res_n["items"]["unchanged"] == 1


# ── 3. Workspaces & Pages CRUD ────────────────────────────────────────────────

def test_workspace_crud():
    ws_data = {"name": "ws_crud", "label": "Workspace CRUD", "sequence": 5}
    ui.create_workspace(ws_data)

    retrieved = ui.get_workspace("ws_crud")
    assert retrieved is not None
    assert retrieved["label"] == "Workspace CRUD"

    ui.update_workspace("ws_crud", {"label": "Updated Workspace CRUD", "sequence": 15})
    updated = ui.get_workspace("ws_crud")
    assert updated["label"] == "Updated Workspace CRUD"

    deleted = ui.delete_workspace("ws_crud")
    assert deleted is True
    assert ui.get_workspace("ws_crud") is None


def test_page_crud():
    page_data = {"name": "page_crud", "title": "Page CRUD", "route": "page-crud"}
    ui.create_page(page_data)

    retrieved = ui.get_page("page_crud")
    assert retrieved is not None
    assert retrieved["title"] == "Page CRUD"

    ui.update_page("page_crud", {"title": "Updated Title", "route": "page-crud-updated"})
    updated = ui.get_page("page_crud")
    assert updated["title"] == "Updated Title"

    deleted = ui.delete_page("page_crud")
    assert deleted is True
    assert ui.get_page("page_crud") is None


# ── 4. Menu Operations Tests ──────────────────────────────────────────────────

def test_menu_operations():
    ws_name = "ws_menu_test"
    ui.create_workspace({"name": ws_name, "label": "Menu Test Workspace", "items": []})

    # Add Menu Item
    item1 = ui.add_menu_item(ws_name, {"name": "item_1", "type": "page", "label": "Item 1", "route": "route-1"})
    assert item1["name"] == "item_1"

    # Add Second Item
    ui.add_menu_item(ws_name, {"name": "item_2", "type": "page", "label": "Item 2", "route": "route-2"})

    ws = ui.get_workspace(ws_name)
    assert len(ws["items"]) == 2

    # Reorder Menu
    reordered = ui.reorder_menu(ws_name, ["item_2", "item_1"])
    assert reordered[0]["name"] == "item_2"
    assert reordered[1]["name"] == "item_1"

    # Update Menu Item
    ui.update_menu_item(ws_name, "item_1", {"name": "item_1", "type": "page", "label": "Item 1 Updated", "route": "route-1"})
    ws_updated = ui.get_workspace(ws_name)
    assert any(i["label"] == "Item 1 Updated" for i in ws_updated["items"])

    # Remove Menu Item
    removed = ui.remove_menu_item(ws_name, "item_1")
    assert removed is True
    ws_final = ui.get_workspace(ws_name)
    assert len(ws_final["items"]) == 1


# ── 5. Component Registry Tests ───────────────────────────────────────────────

def test_component_registry():
    registry = ui.components

    # Test Built-in Rendering
    heading_rendered = registry.render({"type": "heading", "text": "Title", "level": 2})
    assert heading_rendered == {"type": "heading", "text": "Title", "level": 2}

    card_rendered = registry.render({"type": "card", "title": "Card 1", "value": "100", "icon": "star"})
    assert card_rendered["title"] == "Card 1"

    # Test Custom Component Registration
    class CustomWidget(BaseComponentRenderer):
        def render(self, component, context=None):
            return {"type": "custom_widget", "custom_prop": component.get("prop", "default")}

    registry.register("custom_widget", CustomWidget)
    custom_rendered = registry.render({"type": "custom_widget", "prop": "hello"})
    assert custom_rendered == {"type": "custom_widget", "custom_prop": "hello"}

    # Test Unknown Component Error
    with pytest.raises(ComponentRenderError):
        registry.render({"type": "unknown_type"})


# ── 6. Overrides & Developer Update Safety Tests ──────────────────────────────

def test_developer_updates_preserve_admin_overrides():
    dev_ui = {
        "workspaces": [
            {"name": "ws_override_test", "label": "Original Dev Label", "icon": "folder"}
        ]
    }
    ui.setup(dev_ui)

    # Administrator publishes override changing icon -> sparkles
    draft = ui.save_draft({
        "overrides": [
            {
                "target_type": "workspace",
                "target_name": "ws_override_test",
                "changes": {"icon": "sparkles"}
            }
        ]
    })
    ui.publish(draft["draft_id"], user_id="admin_user")

    # Verify initial effective state
    eff1 = ui.get_effective_ui()
    ws1 = next(w for w in eff1["workspaces"] if w["name"] == "ws_override_test")
    assert ws1["label"] == "Original Dev Label"
    assert ws1["icon"] == "sparkles"

    # Developer updates Python configuration changing label -> Updated Dev Label
    dev_ui_updated = {
        "workspaces": [
            {"name": "ws_override_test", "label": "Updated Dev Label", "icon": "folder"}
        ]
    }
    ui.setup(dev_ui_updated)

    # Verify effective state: label comes from developer code update, icon remains admin override!
    eff2 = ui.get_effective_ui()
    ws2 = next(w for w in eff2["workspaces"] if w["name"] == "ws_override_test")
    assert ws2["label"] == "Updated Dev Label"
    assert ws2["icon"] == "sparkles"


# ── 7. User Preferences & Isolation Tests ────────────────────────────────────

def test_user_preferences_isolation():
    dev_ui = {
        "workspaces": [
            {
                "name": "ws_pref",
                "label": "Pref Workspace",
                "items": [
                    {"name": "item_1", "type": "page", "label": "Item 1"},
                    {"name": "item_2", "type": "page", "label": "Item 2"},
                ]
            }
        ]
    }
    ui.setup(dev_ui)

    # User A hides item_2 and sets default workspace
    ui.user_preferences.save({"default_workspace": "ws_pref", "hidden_items": ["item_2"], "favorites": ["item_1"]}, user_id="user_a")

    # User B favorites item_2
    ui.user_preferences.save({"favorites": ["item_2"]}, user_id="user_b")

    # Effective UI User A
    eff_a = ui.get_effective_ui({"user_id": "user_a", "roles": []})
    ws_a = next(w for w in eff_a["workspaces"] if w["name"] == "ws_pref")
    item_names_a = [i["name"] for i in ws_a["items"]]
    assert "item_2" not in item_names_a
    assert ws_a["items"][0]["is_favorite"] is True

    # Effective UI User B
    eff_b = ui.get_effective_ui({"user_id": "user_b", "roles": []})
    ws_b = next(w for w in eff_b["workspaces"] if w["name"] == "ws_pref")
    item_names_b = [i["name"] for i in ws_b["items"]]
    assert "item_2" in item_names_b
    assert any(i["name"] == "item_2" and i.get("is_favorite") for i in ws_b["items"])


# ── 8. Drafts, Non-Mutating Preview & Transactional Publish ───────────────────

def test_drafts_preview_and_publish():
    dev_ui = {
        "workspaces": [
            {"name": "ws_draft_test", "label": "Dev Workspace", "icon": "box"}
        ]
    }
    ui.setup(dev_ui)

    # Save Draft
    draft = ui.save_draft({
        "title": "My Test Draft",
        "overrides": [
            {"target_type": "workspace", "target_name": "ws_draft_test", "changes": {"label": "Draft Overridden Label"}}
        ]
    })
    draft_id = draft["draft_id"]

    # Preview Draft -> Returns predicted effective UI without mutating published state
    preview_eff = ui.preview(draft_id)
    preview_ws = next(w for w in preview_eff["workspaces"] if w["name"] == "ws_draft_test")
    assert preview_ws["label"] == "Draft Overridden Label"

    # Verify Published state is NOT mutated by preview
    published_before = ui.get_effective_ui()
    pub_ws_before = next(w for w in published_before["workspaces"] if w["name"] == "ws_draft_test")
    assert pub_ws_before["label"] == "Dev Workspace"

    # Publish Draft
    ui.publish(draft_id, user_id="admin_user")

    # Verify Published state IS NOW updated
    published_after = ui.get_effective_ui()
    pub_ws_after = next(w for w in published_after["workspaces"] if w["name"] == "ws_draft_test")
    assert pub_ws_after["label"] == "Draft Overridden Label"

    # Verify Audit Entry Created
    logs = RbacAuditLog.query().filter(action="ui.publish").all()
    assert len(logs) > 0
    assert any("admin_user" in l.actor for l in logs)


# ── 9. Versioning & Restoration Tests ────────────────────────────────────────

def test_versioning_and_restoration():
    dev_ui = {
        "workspaces": [{"name": "ws_ver", "label": "Initial Label"}]
    }
    ui.setup(dev_ui)

    # Publish Version 1
    d1 = ui.save_draft({"overrides": [{"target_type": "workspace", "target_name": "ws_ver", "changes": {"label": "Version 1 Label"}}]})
    ui.publish(d1["draft_id"], user_id="admin_user")

    # Publish Version 2
    d2 = ui.save_draft({"overrides": [{"target_type": "workspace", "target_name": "ws_ver", "changes": {"label": "Version 2 Label"}}]})
    ui.publish(d2["draft_id"], user_id="admin_user")

    versions = ui.list_versions()
    assert len(versions) >= 2
    v1_id = versions[-1]["version_id"]

    # Restore Version 1
    ui.restore_version(v1_id, user_id="admin_user")

    # Verify Audit Log
    restore_logs = RbacAuditLog.query().filter(action="ui.restore").all()
    assert len(restore_logs) > 0


# ── 10. Whitelist Decorator & RPC Test ────────────────────────────────────────

def test_whitelist_decorator_and_rpc():
    @thinkdome.whitelist("custom.test_function")
    def my_test_fn(x, y):
        return x + y

    res = thinkdome.call("custom.test_function", x=10, y=20)
    assert res == 30

    # Dynamic ui method execution via thinkdome.call
    eff = thinkdome.call("thinkdome.core.ui.api.get_navigation")
    assert "workspaces" in eff
