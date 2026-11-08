"""Configuration Validator for ThinkDome Dynamic UI Platform."""

from __future__ import annotations

import re
import json
from typing import Any, Dict, List, Optional, Callable
from thinkdome.core.ui.components import ComponentRegistry


SUPPORTED_ITEM_TYPES = {"page", "resource", "report", "url", "group"}


class EntityValidationRule:
    """A declarative rule for validating UI entity configuration objects."""

    def __init__(
        self,
        name: str,
        validator_func: Callable[[Dict[str, Any], Optional[str]], Optional[str]],
        error_code: str = "VALIDATION_FAILED",
    ) -> None:
        self.name = name
        self.validator_func = validator_func
        self.error_code = error_code

    def evaluate(self, config: Dict[str, Any], expected_type: Optional[str] = None) -> Optional[str]:
        return self.validator_func(config, expected_type)


class EntityValidatorPipeline:
    """Pluggable pipeline replacing procedural ladders with declarative entity rules."""

    def __init__(self) -> None:
        self._rules: List[EntityValidationRule] = []
        self._register_default_rules()

    def register_rule(self, rule: EntityValidationRule) -> None:
        self._rules.append(rule)

    def _register_default_rules(self) -> None:
        self.register_rule(EntityValidationRule(
            "object_type",
            lambda cfg, exp: "UI entity configuration must be an object" if not isinstance(cfg, dict) else None
        ))
        self.register_rule(EntityValidationRule(
            "name_presence_and_length",
            lambda cfg, exp: (
                "UI entity name must be a non-empty string of at most 255 characters"
                if not isinstance(cfg.get("name"), str) or not cfg.get("name", "").strip() or len(cfg.get("name", "")) > 255
                else None
            )
        ))
        self.register_rule(EntityValidationRule(
            "name_no_control_characters",
            lambda cfg, exp: (
                "UI entity name contains control characters"
                if isinstance(cfg.get("name"), str) and re.search(r"[\x00-\x1f\x7f]", cfg.get("name", ""))
                else None
            )
        ))
        self.register_rule(EntityValidationRule(
            "expected_entity_type",
            lambda cfg, exp: (
                f"UI entity type must be {exp}"
                if exp and cfg.get("entity_type", exp) != exp
                else None
            )
        ))
        self.register_rule(EntityValidationRule(
            "allowed_roles_schema",
            lambda cfg, exp: self._check_roles(cfg)
        ))
        self.register_rule(EntityValidationRule(
            "payload_json_size",
            lambda cfg, exp: self._check_payload(cfg)
        ))

    @staticmethod
    def _check_roles(cfg: Dict[str, Any]) -> Optional[str]:
        roles = cfg.get("allowed_roles", cfg.get("roles", []))
        if isinstance(roles, str) or not isinstance(roles, (list, tuple, set)):
            return "allowed_roles must be a list of role names"
        if len(roles) > 100 or any(not isinstance(role, str) or not role.strip() or len(role) > 100 for role in roles):
            return "allowed_roles contains an invalid or excessive role list"
        return None

    @staticmethod
    def _check_payload(cfg: Dict[str, Any]) -> Optional[str]:
        try:
            if len(json.dumps(cfg, ensure_ascii=False)) > 1_000_000:
                return "UI entity configuration exceeds the 1 MB limit"
        except (TypeError, ValueError):
            return "UI entity configuration must contain JSON-compatible values"
        return None

    def validate(self, config: Dict[str, Any], expected_type: Optional[str] = None) -> None:
        """Run all registered rules against config; raises ValueError with rule message if invalid."""
        for rule in self._rules:
            error_message = rule.evaluate(config, expected_type)
            if error_message:
                raise ValueError(error_message)


_GLOBAL_ENTITY_PIPELINE = EntityValidatorPipeline()


def _validate_roles(resource: Dict[str, Any], path: str, errors: List[Dict[str, str]]) -> None:
    """Validate the public authorization contract used by every UI resource."""
    roles = resource.get("allowed_roles", resource.get("roles"))
    if roles is not None and not isinstance(roles, (list, tuple, set)):
        errors.append({"path": path, "message": "allowed_roles must be a list of role names"})
    elif roles is not None:
        for idx, role in enumerate(roles):
            if not isinstance(role, str) or not role.strip():
                errors.append({"path": f"{path}[{idx}]", "message": "role names must be non-empty strings"})


class UIValidator:
    """Validates top-level and partial ThinkDome UI configurations."""

    @classmethod
    def validate_entity(cls, config: Dict[str, Any], expected_type: Optional[str] = None) -> None:
        """Validate single UI entity configuration using the pluggable declarative pipeline."""
        _GLOBAL_ENTITY_PIPELINE.validate(config, expected_type)

    @classmethod
    def validate(cls, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Perform comprehensive validation on configuration payload."""
        errors: List[Dict[str, str]] = []

        if not isinstance(config, dict):
            return [{"path": "root", "message": "Configuration must be an object/dict"}]

        # 1. Validate Workspaces
        workspaces = config.get("workspaces", [])
        if not isinstance(workspaces, list):
            errors.append({"path": "workspaces", "message": "workspaces must be a list"})
        else:
            ws_names = set()
            for idx, ws in enumerate(workspaces):
                prefix = f"workspaces[{idx}]"
                if not isinstance(ws, dict):
                    errors.append({"path": prefix, "message": "workspace item must be an object"})
                    continue

                ws_name = ws.get("name")
                if not ws_name:
                    errors.append({"path": f"{prefix}.name", "message": "name is required"})
                elif ws_name in ws_names:
                    errors.append({"path": f"{prefix}.name", "message": f"duplicate workspace name '{ws_name}'"})
                else:
                    ws_names.add(ws_name)

                if not ws.get("label"):
                    errors.append({"path": f"{prefix}.label", "message": "label is required"})
                _validate_roles(ws, f"{prefix}.allowed_roles", errors)

                # Validate workspace items/menus
                items = ws.get("items", [])
                cls._validate_menu_items(items, f"{prefix}.items", errors, set())

        # 2. Validate Pages
        pages = config.get("pages", [])
        if not isinstance(pages, list):
            errors.append({"path": "pages", "message": "pages must be a list"})
        else:
            page_names = set()
            for idx, page in enumerate(pages):
                prefix = f"pages[{idx}]"
                if not isinstance(page, dict):
                    errors.append({"path": prefix, "message": "page item must be an object"})
                    continue

                p_name = page.get("name")
                if not p_name:
                    errors.append({"path": f"{prefix}.name", "message": "name is required"})
                elif p_name in page_names:
                    errors.append({"path": f"{prefix}.name", "message": f"duplicate page name '{p_name}'"})
                else:
                    page_names.add(p_name)

                if not page.get("title"):
                    errors.append({"path": f"{prefix}.title", "message": "title is required"})

                if not page.get("route"):
                    errors.append({"path": f"{prefix}.route", "message": "route is required"})
                _validate_roles(page, f"{prefix}.allowed_roles", errors)

                # Validate layout / components inside page
                layout = page.get("layout", [])
                cls._validate_components(layout, f"{prefix}.layout", errors)

        # 3. Validate top-level components if provided
        components = config.get("components", [])
        if not isinstance(components, list):
            errors.append({"path": "components", "message": "components must be a list"})
        else:
            cls._validate_components(components, "components", errors)

        return errors

    @classmethod
    def _validate_menu_items(
        cls, items: Any, path_prefix: str, errors: List[Dict[str, str]], item_names: set
    ) -> None:
        """Recursively validate menu items."""
        if not isinstance(items, list):
            errors.append({"path": path_prefix, "message": "items must be a list"})
            return

        for idx, item in enumerate(items):
            prefix = f"{path_prefix}[{idx}]"
            if not isinstance(item, dict):
                errors.append({"path": prefix, "message": "menu item must be an object"})
                continue

            name = item.get("name")
            if not name:
                errors.append({"path": f"{prefix}.name", "message": "name is required"})
            elif name in item_names:
                errors.append({"path": f"{prefix}.name", "message": f"duplicate item name '{name}'"})
            else:
                item_names.add(name)

            itype = item.get("type")
            _validate_roles(item, f"{prefix}.allowed_roles", errors)
            if not itype:
                errors.append({"path": f"{prefix}.type", "message": "type is required"})
            elif itype not in SUPPORTED_ITEM_TYPES:
                errors.append({"path": f"{prefix}.type", "message": f"unsupported item type '{itype}'"})

            if itype == "group":
                child_items = item.get("items", [])
                cls._validate_menu_items(child_items, f"{prefix}.items", errors, item_names)

    @classmethod
    def _validate_components(cls, components: Any, path_prefix: str, errors: List[Dict[str, str]]) -> None:
        """Recursively validate components and layouts."""
        if not isinstance(components, list):
            errors.append({"path": path_prefix, "message": "components layout must be a list"})
            return

        registry = ComponentRegistry.get_instance()
        for idx, comp in enumerate(components):
            prefix = f"{path_prefix}[{idx}]"
            if not isinstance(comp, dict):
                errors.append({"path": prefix, "message": "component must be an object"})
                continue

            ctype = comp.get("type")
            if not ctype:
                errors.append({"path": f"{prefix}.type", "message": "component type is required"})
                continue

            if not registry.get(ctype):
                errors.append({"path": f"{prefix}.type", "message": f"unsupported component type '{ctype}'"})
                continue

            # Recursive validation for layout containers
            if ctype in ("row", "column"):
                if ctype == "row":
                    cols = comp.get("columns", [])
                    if isinstance(cols, list):
                        for c_idx, col in enumerate(cols):
                            if isinstance(col, dict):
                                cls._validate_components(col.get("components", []), f"{prefix}.columns[{c_idx}].components", errors)
                elif ctype == "column":
                    cls._validate_components(comp.get("components", []), f"{prefix}.components", errors)
            elif ctype in ("grid", "stack", "section"):
                cls._validate_components(comp.get("components", []), f"{prefix}.components", errors)
            elif ctype == "tabs":
                tab_items = comp.get("items", [])
                if isinstance(tab_items, list):
                    for t_idx, tab in enumerate(tab_items):
                        if isinstance(tab, dict):
                            cls._validate_components(tab.get("components", []), f"{prefix}.items[{t_idx}].components", errors)
