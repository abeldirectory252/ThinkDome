"""Component Registry and Rendering Primitives for ThinkDome Dynamic UI Platform."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type, Union


class ComponentRenderError(Exception):
    """Exception raised when rendering an unknown or invalid component."""
    pass


class BaseComponentRenderer:
    """Base interface for component renderers."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Transform component configuration payload into rendered structure."""
        raise NotImplementedError


class HeadingComponent(BaseComponentRenderer):
    """Renders text heading elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "heading",
            "text": component.get("text", ""),
            "level": int(component.get("level", 1)),
        }


class CardComponent(BaseComponentRenderer):
    """Renders card elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "card",
            "title": component.get("title", ""),
            "value": component.get("value", ""),
            "icon": component.get("icon", "box"),
        }


class StatComponent(BaseComponentRenderer):
    """Renders metric/statistic elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "stat",
            "label": component.get("label", ""),
            "value": component.get("value", 0),
            "icon": component.get("icon", "activity"),
        }


class ChartComponent(BaseComponentRenderer):
    """Renders chart elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "chart",
            "title": component.get("title", ""),
            "data": component.get("data", {}),
        }


class TableComponent(BaseComponentRenderer):
    """Renders data table elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "table",
            "title": component.get("title", ""),
            "data": component.get("data", {}),
        }


class LinkComponent(BaseComponentRenderer):
    """Renders navigation link elements."""

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "link",
            "label": component.get("label", ""),
            "route": component.get("route", ""),
        }


# ── Layout Primitives ─────────────────────────────────────────────────────────

class RowLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rendered_cols = []
        for col in component.get("columns", []):
            rendered_cols.append({
                "width": col.get("width", 12),
                "components": [
                    ComponentRegistry.get_instance().render(c, context)
                    for c in col.get("components", [])
                ],
            })
        return {"type": "row", "columns": rendered_cols}


class ColumnLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "column",
            "width": component.get("width", 12),
            "components": [
                ComponentRegistry.get_instance().render(c, context)
                for c in component.get("components", [])
            ],
        }


class GridLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "grid",
            "columns": component.get("columns", 2),
            "gap": component.get("gap", 16),
            "components": [
                ComponentRegistry.get_instance().render(c, context)
                for c in component.get("components", [])
            ],
        }


class StackLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "stack",
            "direction": component.get("direction", "vertical"),
            "gap": component.get("gap", 8),
            "components": [
                ComponentRegistry.get_instance().render(c, context)
                for c in component.get("components", [])
            ],
        }


class SectionLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "type": "section",
            "title": component.get("title", ""),
            "components": [
                ComponentRegistry.get_instance().render(c, context)
                for c in component.get("components", [])
            ],
        }


class TabsLayout(BaseComponentRenderer):
    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        items = []
        for item in component.get("items", []):
            items.append({
                "label": item.get("label", ""),
                "components": [
                    ComponentRegistry.get_instance().render(c, context)
                    for c in item.get("components", [])
                ],
            })
        return {"type": "tabs", "items": items}


# ── Registry ──────────────────────────────────────────────────────────────────

class ComponentRegistry:
    """Registry managing dynamic and extensible component renderers."""

    _instance: Optional[ComponentRegistry] = None

    def __init__(self) -> None:
        self._renderers: Dict[str, Any] = {}
        self._register_defaults()

    @classmethod
    def get_instance(cls) -> ComponentRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _register_defaults(self) -> None:
        """Register built-in component and layout primitives."""
        self.register("heading", HeadingComponent)
        self.register("card", CardComponent)
        self.register("stat", StatComponent)
        self.register("chart", ChartComponent)
        self.register("table", TableComponent)
        self.register("link", LinkComponent)
        self.register("row", RowLayout)
        self.register("column", ColumnLayout)
        self.register("grid", GridLayout)
        self.register("stack", StackLayout)
        self.register("section", SectionLayout)
        self.register("tabs", TabsLayout)

    def register(self, name: str, renderer: Union[Type[BaseComponentRenderer], BaseComponentRenderer, Callable]) -> None:
        """Register a component name to a renderer class, instance, or callable."""
        self._renderers[name] = renderer

    def get(self, name: str) -> Optional[Any]:
        """Fetch registered renderer for a given component type."""
        return self._renderers.get(name)

    def render(self, component: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Render a single component configuration payload."""
        comp_type = component.get("type")
        if not comp_type:
            raise ComponentRenderError("Component payload missing required 'type' attribute")

        renderer = self.get(comp_type)
        if not renderer:
            raise ComponentRenderError(f"Unknown component type '{comp_type}'")

        if isinstance(renderer, type) and issubclass(renderer, BaseComponentRenderer):
            return renderer().render(component, context)
        elif isinstance(renderer, BaseComponentRenderer):
            return renderer.render(component, context)
        elif callable(renderer):
            return renderer(component, context)
        else:
            raise ComponentRenderError(f"Invalid renderer registered for type '{comp_type}'")
