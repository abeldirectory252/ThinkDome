"""Framework UI Registry & Declarative Framework Decorators for ThinkDome.

In Frappe/ERPNext framework style, Python app modules register Workspaces and
Pages declaratively using framework decorators or config files:

    import thinkdome

    @thinkdome.ui.workspace(
        name="developer",
        label="AI & Dev Engineering",
        icon="🚀",
        allowed_roles=["AGENT_STANDARD", "SUPER_ADMIN"]
    )
    class DeveloperWorkspace:
        items = [
            {"name": "sandboxes", "label": "Sandboxes Studio", "route": "sandboxes", "icon": "box"},
            {"name": "console", "label": "Console & IDE", "route": "console", "icon": "terminal"},
        ]

    @thinkdome.ui.page(
        name="sandboxes",
        title="Sandboxes Studio",
        allowed_roles=["AGENT_STANDARD", "SUPER_ADMIN"]
    )
    class SandboxesPage:
        layout = [
            {"type": "heading", "text": "AI Sandboxes Studio & Container Runtimes", "level": 1}
        ]

On server startup, `sync_registered_ui()` syncs all Python-declared frameworks
into the database ORM (`UIDeveloperConfig`) idempotently.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type, Union

logger = logging.getLogger(__name__)


class FrameworkUIRegistry:
    """Singleton registry for framework-declared Workspaces and Pages."""

    _instance: Optional[FrameworkUIRegistry] = None

    def __init__(self) -> None:
        self._workspaces: Dict[str, Dict[str, Any]] = {}
        self._pages: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> FrameworkUIRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_workspace(self, name: str, config: Dict[str, Any]) -> None:
        """Register a workspace configuration."""
        config["name"] = name
        if "label" not in config:
            config["label"] = name.replace("_", " ").title()
        self._workspaces[name] = config
        logger.debug("Framework registered workspace: %s", name)

    def register_page(self, name: str, config: Dict[str, Any]) -> None:
        """Register a page configuration."""
        config["name"] = name
        config["route"] = config.get("route", name)
        if "title" not in config:
            config["title"] = name.replace("_", " ").title()
        self._pages[name] = config
        logger.debug("Framework registered page: %s", name)

    def export_config(self) -> Dict[str, Any]:
        """Export full declarative configuration dictionary for UIManager.setup()."""
        return {
            "workspaces": list(self._workspaces.values()),
            "pages": list(self._pages.values()),
        }

    def sync_to_db(self) -> Dict[str, Any]:
        """Sync all registered framework Workspaces & Pages into UIManager DB tables."""
        from thinkdome.core.ui.service import UIManager
        config = self.export_config()
        if not config["workspaces"] and not config["pages"]:
            logger.debug("No framework UI registered to sync.")
            return {}
        mgr = UIManager()
        return mgr.setup(config)


# ── Framework Declarative Decorators ───────────────────────────────────────────

def workspace(
    name: str,
    label: Optional[str] = None,
    sequence: int = 10,
    icon: str = "▦",
    description: str = "",
    allowed_roles: Optional[List[str]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    shortcuts: Optional[List[Dict[str, Any]]] = None,
    number_cards: Optional[List[Dict[str, Any]]] = None,
    card_groups: Optional[List[Dict[str, Any]]] = None,
):
    """Decorator or function to register a Framework Workspace."""

    def decorator(cls_or_dict: Union[Type, Dict[str, Any]]) -> Any:
        cfg = {
            "label": label or (cls_or_dict.__name__ if hasattr(cls_or_dict, "__name__") else name.title()),
            "sequence": sequence,
            "icon": icon,
            "description": description,
            "allowed_roles": allowed_roles or ["SUPER_ADMIN", "AGENT_STANDARD"],
            "items": items or getattr(cls_or_dict, "items", []),
            "shortcuts": shortcuts or getattr(cls_or_dict, "shortcuts", []),
            "number_cards": number_cards or getattr(cls_or_dict, "number_cards", []),
            "card_groups": card_groups or getattr(cls_or_dict, "card_groups", []),
        }
        FrameworkUIRegistry.get_instance().register_workspace(name, cfg)
        return cls_or_dict

    if isinstance(name, dict):
        d = name
        wname = d["name"]
        FrameworkUIRegistry.get_instance().register_workspace(wname, d)
        return d

    return decorator


def page(
    name: str,
    title: Optional[str] = None,
    allowed_roles: Optional[List[str]] = None,
    layout: Optional[List[Dict[str, Any]]] = None,
):
    """Decorator or function to register a Framework Dynamic Page."""

    def decorator(cls_or_dict: Union[Type, Dict[str, Any]]) -> Any:
        cfg = {
            "title": title or (cls_or_dict.__name__ if hasattr(cls_or_dict, "__name__") else name.title()),
            "allowed_roles": allowed_roles or ["SUPER_ADMIN", "AGENT_STANDARD"],
            "layout": layout or getattr(cls_or_dict, "layout", []),
        }
        FrameworkUIRegistry.get_instance().register_page(name, cfg)
        return cls_or_dict

    if isinstance(name, dict):
        d = name
        pname = d["name"]
        FrameworkUIRegistry.get_instance().register_page(pname, d)
        return d

    return decorator
