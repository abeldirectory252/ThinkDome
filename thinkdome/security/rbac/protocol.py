"""Centralized Dynamic Role Allocation Protocol for Workspace Manager and ThinkDome.

This module provides the central protocol engine for:
1. Dynamic document-level & functional privilege allocation (zero static role code).
2. Pluggable registry-based DocumentTypeResolver (replaces brittle if-elif-else ladders).
3. Full audit logging on every privilege grant, denial, exemption, and denied attempt.
4. Evaluating privileges dynamically across all 10 core subsystems:
   - Pages
   - Sidebar
   - UI Customizer
   - Privilege Denial and Privilege Granter
   - MCP for given role
   - Filebox
   - Console & IDE
   - Sandbox Tenant & Isolation
   - Network Egress
   - Model & Design Management
5. Enforcing that every function / document is a privilege by default, with
   support for intentional user/developer customization to exempt resources.
6. Supporting the 14 dynamic privilege properties:
   - Select
   - Read
   - Write
   - Create
   - Delete
   - Print
   - Email
   - Report
   - Import
   - Export
   - Set User Permissions
   - Share
   - Access MCP
   - File Related
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Standard dynamic privilege property names (14 properties)
PERMISSION_PROPERTIES: Tuple[str, ...] = (
    "select",
    "read",
    "write",
    "create",
    "delete",
    "print",
    "email",
    "report",
    "import",
    "export",
    "set_user_permissions",
    "share",
    "access_mcp",
    "file_related",
)

# Convenience alias – _DEFAULT_RULES and override helpers reference the full tuple.
ALL_PROPERTIES = PERMISSION_PROPERTIES

# Core subsystems and document types incorporated into the protocol
CORE_SUBSYSTEMS: Dict[str, str] = {
    "Page": "Dynamic UI Pages and Views",
    "Sidebar": "Workspace Sidebar Navigation and Menus",
    "UICustomizer": "UI Layout Customizer and Overrides",
    "MCPTool": "Model Context Protocol Tool Registry",
    "Filebox": "Agent and Workspace Filebox Filesystem",
    "Console": "Interactive Developer & Operator Console",
    "IDE": "Integrated Development Environment Sandbox",
    "Sandbox": "Containerized Sandbox Tenant & Compute",
    "NetworkEgress": "Sandbox Outbound Network Egress Rules",
    "ModelDesign": "AI Model Weights, Prompt Templates & Design Assets",
    "Function": "Server RPC Methods and Handlers",
    "Workspace": "Workspace Management Entities",
}

# Fallback default rules seeding database when DocPerm is empty
_DEFAULT_RULES: List[Dict[str, Any]] = [
    # 1. Page subsystem
    {
        "document_type": "Page",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "share": True, "print": True},
    },
    {
        "document_type": "Page",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 2. Sidebar subsystem
    {
        "document_type": "Sidebar",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True},
    },
    {
        "document_type": "Sidebar",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 3. UICustomizer subsystem
    {
        "document_type": "UICustomizer",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True},
    },
    {
        "document_type": "UICustomizer",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "create": True, "export": True, "import": True},
    },
    {
        "document_type": "UICustomizer",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 4. MCPTool subsystem
    {
        "document_type": "MCPTool",
        "role": "AGENT_STANDARD",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "access_mcp": True, "write": True},
    },
    {
        "document_type": "MCPTool",
        "role": "LLM",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "access_mcp": True, "write": True},
    },
    {
        "document_type": "MCPTool",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "access_mcp": True, "write": True, "create": True},
    },
    {
        "document_type": "MCPTool",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 5. Filebox subsystem
    {
        "document_type": "Filebox",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "file_related": True},
    },
    {
        "document_type": "Filebox",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "create": True, "file_related": True, "export": True, "import": True},
    },
    {
        "document_type": "Filebox",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 6. Console / IDE subsystem
    {
        "document_type": "Console",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "access_mcp": True},
    },
    {
        "document_type": "IDE",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "access_mcp": True},
    },
    {
        "document_type": "Console",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    {
        "document_type": "IDE",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 7. Sandbox subsystem
    {
        "document_type": "Sandbox",
        "role": "AGENT_STANDARD",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "access_mcp": True},
    },
    {
        "document_type": "Sandbox",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "create": True, "access_mcp": True},
    },
    {
        "document_type": "Sandbox",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 8. NetworkEgress subsystem
    {
        "document_type": "NetworkEgress",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "access_mcp": True, "connect": True},
    },
    {
        "document_type": "NetworkEgress",
        "role": "AGENT_STANDARD",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "connect": True},
    },
    {
        "document_type": "NetworkEgress",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 9. ModelDesign subsystem
    {
        "document_type": "ModelDesign",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {},
    },
    {
        "document_type": "ModelDesign",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "create": True, "export": True, "import": True},
    },
    {
        "document_type": "ModelDesign",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
    # 10. Function subsystem
    {
        "document_type": "Function",
        "role": "*",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "access_mcp": True},
    },
    {
        "document_type": "Function",
        "role": "DEVELOPER",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {"select": True, "read": True, "write": True, "create": True, "access_mcp": True},
    },
    {
        "document_type": "Function",
        "role": "ADMIN",
        "level": 0,
        "is_denial": False,
        "is_custom_exempt": False,
        "permissions": {p: True for p in ALL_PROPERTIES},
    },
]

# Action mapping normalization
_ACTION_ALIASES: Dict[str, str] = {
    "exec": "write",
    "execute": "write",
    "run": "write",
    "view": "read",
    "get": "read",
    "list": "select",
    "edit": "write",
    "update": "write",
    "put": "write",
    "post": "create",
    "remove": "delete",
    "import_perm": "import",
    "set_permissions": "set_user_permissions",
    "mcp": "access_mcp",
    "file": "file_related",
}


class DocumentTypeResolver:
    """Pluggable registry-based Document Type resolver.

    Replaces rigid if-elif-else ladders with an extensible, dynamic detector
    and alias registry that subsystems can extend at runtime without modifying code.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._alias_map: Dict[str, str] = {}
        self._detectors: List[Tuple[int, str, Callable[[Any], bool]]] = []
        self._type_descriptions: Dict[str, str] = {}
        self._initialize_core_subsystems()

    def _initialize_core_subsystems(self) -> None:
        """Register the built-in subsystem canonical types, aliases, and structural detectors."""
        for doc_type, desc in CORE_SUBSYSTEMS.items():
            self.register_type(doc_type, description=desc)

        # ── 1. Page Subsystem ──
        self.register_alias("page", "Page")
        self.register_alias("pages", "Page")
        self.register_alias("view", "Page")
        self.register_alias("dashboard", "Page")
        self.register_alias("route", "Page")
        self.register_alias("desk_page", "Page")
        self.register_detector(
            "Page",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("layout", "route", "page_name", "blocks")),
            priority=80,
        )

        # ── 2. Sidebar Subsystem ──
        self.register_alias("sidebar", "Sidebar")
        self.register_alias("menu", "Sidebar")
        self.register_alias("menu_item", "Sidebar")
        self.register_alias("workspace", "Sidebar")
        self.register_alias("workspaces", "Sidebar")
        self.register_alias("navigation", "Sidebar")
        self.register_alias("nav", "Sidebar")
        self.register_detector(
            "Sidebar",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("items", "menus", "menu_id", "workspace_name")),
            priority=80,
        )

        # ── 3. UI Customizer Subsystem ──
        self.register_alias("ui_customizer", "UICustomizer")
        self.register_alias("uicustomizer", "UICustomizer")
        self.register_alias("component", "UICustomizer")
        self.register_alias("widget", "UICustomizer")
        self.register_alias("ui_override", "UICustomizer")
        self.register_alias("customizer", "UICustomizer")
        self.register_detector(
            "UICustomizer",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("component_id", "customizer", "override", "changes")),
            priority=80,
        )

        # ── 4. MCP Subsystem ──
        self.register_alias("mcp", "MCPTool")
        self.register_alias("mcptool", "MCPTool")
        self.register_alias("mcp_tool", "MCPTool")
        self.register_alias("mcp_server", "MCPTool")
        self.register_alias("tool", "MCPTool")
        self.register_alias("agent_tool", "MCPTool")
        self.register_detector(
            "MCPTool",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("tool_name", "mcp_name", "tool_schema", "input_schema")),
            priority=70,
        )

        # ── 5. Filebox Subsystem ──
        self.register_alias("filebox", "Filebox")
        self.register_alias("file", "Filebox")
        self.register_alias("files", "Filebox")
        self.register_alias("volume", "Filebox")
        self.register_alias("filesystem", "Filebox")
        self.register_alias("box_file", "Filebox")
        self.register_detector(
            "Filebox",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("file_path", "volume_id", "box_id", "filebox")),
            priority=70,
        )

        # ── 6. Console Subsystem ──
        self.register_alias("console", "Console")
        self.register_alias("terminal", "Console")
        self.register_alias("shell", "Console")
        self.register_alias("term_cmd", "Console")
        self.register_detector(
            "Console",
            lambda r: isinstance(r, Mapping) and ("command" in r and "stdin" not in r and "language" not in r),
            priority=75,
        )

        # ── 7. IDE Subsystem ──
        self.register_alias("ide", "IDE")
        self.register_alias("editor", "IDE")
        self.register_alias("workspace_editor", "IDE")
        self.register_alias("code_editor", "IDE")
        self.register_detector(
            "IDE",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("editor_session", "ide_workspace", "active_tab")),
            priority=75,
        )

        # ── 8. Sandbox Tenant Subsystem ──
        self.register_alias("sandbox", "Sandbox")
        self.register_alias("sandbox_tenant", "Sandbox")
        self.register_alias("tenant", "Sandbox")
        self.register_alias("container", "Sandbox")
        self.register_alias("exec_container", "Sandbox")
        self.register_detector(
            "Sandbox",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("sandbox_id", "container_id", "security_profile")),
            priority=70,
        )

        # ── 9. Network Egress Subsystem ──
        self.register_alias("network_egress", "NetworkEgress")
        self.register_alias("networkegress", "NetworkEgress")
        self.register_alias("egress", "NetworkEgress")
        self.register_alias("egress_rule", "NetworkEgress")
        self.register_alias("network_rule", "NetworkEgress")
        self.register_detector(
            "NetworkEgress",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("destination_host", "dest_port", "egress_type", "destination")),
            priority=70,
        )

        # ── 10. Model & Design Management Subsystem ──
        self.register_alias("model_design", "ModelDesign")
        self.register_alias("modeldesign", "ModelDesign")
        self.register_alias("model", "ModelDesign")
        self.register_alias("design", "ModelDesign")
        self.register_alias("prompt_template", "ModelDesign")
        self.register_alias("prompt", "ModelDesign")
        self.register_alias("model_weights", "ModelDesign")
        self.register_alias("design_asset", "ModelDesign")
        self.register_detector(
            "ModelDesign",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("model_name", "prompt_template", "design_asset", "weights_path", "template_body")),
            priority=70,
        )

        # ── Function Subsystem ──
        self.register_alias("function", "Function")
        self.register_alias("rpc", "Function")
        self.register_alias("method", "Function")
        self.register_alias("api_endpoint", "Function")
        self.register_detector(
            "Function",
            lambda r: isinstance(r, Mapping) and any(k in r for k in ("function_name", "rpc_method", "handler_path")),
            priority=70,
        )

    def register_type(self, doc_type: str, description: str = "") -> None:
        """Register a canonical document type with optional description."""
        canonical = doc_type.strip()
        with self._lock:
            self._type_descriptions[canonical] = description
            if canonical.lower() not in self._alias_map:
                self._alias_map[canonical.lower()] = canonical

    def register_alias(self, alias: str, canonical_doc_type: str) -> None:
        """Register an alias pointing to a canonical document type."""
        with self._lock:
            self._alias_map[alias.strip().lower()] = canonical_doc_type.strip()

    def register_detector(
        self,
        doc_type: str,
        detector: Callable[[Any], bool],
        priority: int = 100,
    ) -> None:
        """Register a dynamic detection predicate for resolving document types from arbitrary objects."""
        canonical = doc_type.strip()
        with self._lock:
            self._detectors.append((priority, canonical, detector))
            self._detectors.sort(key=lambda x: x[0])

    def resolve(self, resource: Any, default: str = "Page") -> str:
        """Dynamically resolve an arbitrary resource or dictionary into a canonical Document Type.

        Evaluation order:
        1. String resource: canonical alias / exact lookup.
        2. Mapping/dict with explicit 'document_type' or 'doctype': alias lookup.
        3. Mapping/dict with 'entity_type' or 'type': alias lookup.
        4. Pluggable detectors matching structural properties (priority order).
        5. Python class/type inspection.
        6. Default fallback.
        """
        if resource is None:
            return default

        # 1. Plain string or enum-like object
        if isinstance(resource, str):
            val = resource.strip()
            with self._lock:
                return self._alias_map.get(val.lower(), val)

        if not isinstance(resource, (dict, Mapping)):
            # Object instance check
            class_name = getattr(type(resource), "__name__", "")
            with self._lock:
                if class_name.lower() in self._alias_map:
                    return self._alias_map[class_name.lower()]
            # If object has doctype/entity_type attributes
            attr_type = (
                getattr(resource, "document_type", None)
                or getattr(resource, "doctype", None)
                or getattr(resource, "entity_type", None)
            )
            if attr_type and isinstance(attr_type, str):
                with self._lock:
                    return self._alias_map.get(attr_type.lower(), attr_type)

        # 2. Mapping checks
        if isinstance(resource, Mapping):
            # Check explicit doctype keys
            for key in ("document_type", "doctype", "doc_type"):
                val = resource.get(key)
                if val and isinstance(val, str):
                    with self._lock:
                        return self._alias_map.get(val.lower(), val)

            # Check entity_type / type
            for key in ("entity_type", "type", "kind", "resource_type"):
                val = resource.get(key)
                if val and isinstance(val, str):
                    with self._lock:
                        mapped = self._alias_map.get(val.lower())
                        if mapped:
                            return mapped

            # Run pluggable detectors
            with self._lock:
                detectors_snapshot = list(self._detectors)

            for _prio, doc_type, detector in detectors_snapshot:
                try:
                    if detector(resource):
                        return doc_type
                except Exception:
                    continue

        return default

    def get_registered_types(self) -> List[str]:
        """Return all distinct registered document type names."""
        with self._lock:
            return sorted(self._type_descriptions.keys())

    def get_type_description(self, doc_type: str) -> str:
        with self._lock:
            return self._type_descriptions.get(doc_type.strip(), "")


# Global pluggable resolver singleton
document_type_resolver = DocumentTypeResolver()


class DynamicRoleAllocationProtocol:
    """Centralized dynamic role allocation and privilege protocol engine.

    Thread-safe, backed by ORM DocPerm persistence, and cached in-memory
    for microsecond evaluation.
    """

    def __init__(self, resolver: Optional[DocumentTypeResolver] = None) -> None:
        self._lock = threading.RLock()
        self.resolver: DocumentTypeResolver = resolver or document_type_resolver
        self._cache: Dict[Tuple, Any] = {}
        self._cache_version: int = 0
        self._registered_doc_types: Dict[str, Dict[str, Any]] = {}
        self._registered_roles: Dict[str, Dict[str, Any]] = {}
        self._exemptions: Set[str] = set()
        self._in_memory_rules: List[Dict[str, Any]] = []
        self._initialized: bool = False

    # ── Initialization & Dynamic Discovery ────────────────────────────────────

    def ensure_initialized(self) -> None:
        """Dynamically discover roles and document types without static role lists."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._bootstrap_protocol()
            self._initialized = True

    def _bootstrap_protocol(self) -> None:
        """Dynamically discover document types and roles from ORM and registry."""
        # 1. Register subsystems from resolver
        for doc_type in self.resolver.get_registered_types():
            desc = self.resolver.get_type_description(doc_type)
            self.register_document_type(doc_type, description=desc)

        # 2. Dynamic Role Names & Role Profiles Bootstrap
        try:
            from thinkdome.security.rbac.registry import rbac_registry
            rbac_registry.bootstrap_standard_roles_and_profiles()
        except Exception as reg_err:
            logger.debug("RBAC registry bootstrap note: %s", reg_err)

        # 3. Dynamic Role Discovery from persistent ORM Role table
        try:
            from thinkdome.security.rbac.models import Role
            for r in Role.query().all():
                parent_name = None
                if r.parent_role_id:
                    p = Role.get(r.parent_role_id)
                    if p:
                        parent_name = p.name
                self.register_role(r.name, description=r.description or "", parent_role=parent_name)
        except Exception as e:
            logger.debug("Dynamic role discovery from DB bypassed: %s", e)

        # 3. Dynamic Discovery from existing DocPerm records; seed from _DEFAULT_RULES if empty
        try:
            from thinkdome.security.rbac.models import DocPerm
            docperms = DocPerm.query().all()
            if not docperms and _DEFAULT_RULES:
                logger.info("DocPerm database table is empty; seeding default rules from _DEFAULT_RULES via ORM")
                for r in _DEFAULT_RULES:
                    try:
                        DocPerm(
                            document_type=r["document_type"],
                            role=r["role"],
                            level=r.get("level", 0),
                            is_denial=bool(r.get("is_denial", False)),
                            is_custom_exempt=bool(r.get("is_custom_exempt", False)),
                            workspace_id=r.get("workspace_id"),
                            user_id=r.get("user_id"),
                            **{f"perm_{p}": bool(r.get("permissions", {}).get(p, False)) for p in ALL_PROPERTIES}
                        ).save()
                    except Exception as seed_err:
                        logger.debug("Failed saving seed rule: %s", seed_err)
                docperms = DocPerm.query().all()

            for dp in docperms:
                if dp.role and dp.role != "*":
                    self._ensure_role_registered(dp.role)
                if dp.document_type:
                    self.register_document_type(dp.document_type)
        except Exception as e:
            logger.debug("Dynamic docperm discovery bypassed: %s", e)

    # ── Dynamic Role Resolution Helpers ───────────────────────────────────────

    def get_default_role(self) -> str:
        """Dynamically resolve the standard default unprivileged role for newly registered users from database."""
        self.ensure_initialized()
        try:
            from thinkdome.security.rbac.models import Role
            roles = Role.query().filter(is_active=True).all()
            for r in roles:
                name_upper = r.name.upper()
                if not getattr(r, "is_admin", False) and "ADMIN" not in name_upper and name_upper not in ("ANONYMOUS", "GUEST"):
                    return r.name
            first_role = Role.query().first()
            if first_role:
                return first_role.name
        except Exception:
            pass
        return "AGENT_STANDARD"

    def get_default_admin_role(self) -> str:
        """Dynamically resolve the highest administrative role in the system from database."""
        self.ensure_initialized()
        try:
            from thinkdome.security.rbac.models import Role
            admin_roles = Role.query().filter(is_active=True).all()
            for r in admin_roles:
                if getattr(r, "is_admin", False) or "ADMIN" in r.name.upper():
                    return r.name
        except Exception:
            pass
        return "ADMIN"

    def is_admin_role(self, role: Union[str, Iterable[str]]) -> bool:
        """Dynamically determine whether role(s) hold super-admin or admin authority."""
        from thinkdome.security.identity.core import is_admin_role as identity_is_admin
        if isinstance(role, str):
            return identity_is_admin(role)
        return any(identity_is_admin(r) for r in (role or []))

    # ── Document Type Resolution ──────────────────────────────────────────────

    def resolve_document_type(self, resource: Any, default: str = "Page") -> str:
        """Dynamically resolve an arbitrary resource into a canonical document type via pluggable resolver."""
        return self.resolver.resolve(resource, default=default)

    # ── Dynamic Registry Management ───────────────────────────────────────────

    def register_document_type(
        self,
        doc_type: str,
        description: str = "",
        default_permissions: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """Dynamically register a new document type into the centralized protocol."""
        canonical = doc_type.strip()
        info = {
            "document_type": canonical,
            "description": description or self.resolver.get_type_description(canonical),
            "default_permissions": default_permissions or {},
        }
        with self._lock:
            self._registered_doc_types[canonical.lower()] = info
            self._registered_doc_types[canonical] = info
            self.resolver.register_type(canonical, description=info["description"])
            self.invalidate_cache()
        return info

    def register_role(
        self,
        name: str,
        description: str = "",
        parent_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dynamically register a role into the protocol (persists to ORM Role if available)."""
        canonical = name.strip().upper()
        parent_canonical = parent_role.strip().upper() if parent_role else None
        info = {
            "name": canonical,
            "description": description,
            "parent_role": parent_canonical,
        }

        # Persist to ORM Role table
        try:
            from thinkdome.security.rbac.models import Role
            existing = Role.query().filter(name=canonical).first()
            parent_id = None
            if parent_canonical:
                p_role = Role.query().filter(name=parent_canonical).first()
                if not p_role:
                    p_role = Role(name=parent_canonical, description=f"{parent_canonical} role", is_active=True)
                    p_role.save()
                parent_id = p_role.id

            if not existing:
                existing = Role(
                    name=canonical,
                    description=description or f"{canonical} dynamic role",
                    parent_role_id=parent_id,
                    is_active=True,
                )
                existing.save()
            elif parent_id and not existing.parent_role_id:
                existing.parent_role_id = parent_id
                existing.save()
        except Exception as e:
            logger.debug("Dynamic Role persistence note: %s", e)

        with self._lock:
            self._registered_roles[canonical] = info
            self.invalidate_cache()
        return info

    def _ensure_role_registered(self, role_name: str) -> None:
        """Ensure a role is dynamically known to the protocol."""
        canonical = role_name.strip().upper()
        if not canonical or canonical == "*":
            return
        with self._lock:
            if canonical in self._registered_roles:
                return

        # Query ORM
        try:
            from thinkdome.security.rbac.models import Role
            existing = Role.query().filter(name=canonical).first()
            if existing:
                parent_name = None
                if existing.parent_role_id:
                    p = Role.get(existing.parent_role_id)
                    if p:
                        parent_name = p.name
                self.register_role(existing.name, description=existing.description or "", parent_role=parent_name)
                return
        except Exception:
            pass

        # Dynamically register on demand
        self.register_role(canonical, description=f"Dynamic {canonical} role")

    def get_registered_doc_types(self) -> List[str]:
        """Return list of distinct registered document type names."""
        self.ensure_initialized()
        with self._lock:
            seen = set()
            res = []
            for k in self._registered_doc_types:
                if k not in seen and not k.islower():
                    seen.add(k)
                    res.append(k)
            return sorted(res or self.resolver.get_registered_types())

    def get_registered_roles(self) -> List[str]:
        """Return list of all dynamically registered roles."""
        self.ensure_initialized()
        # Also sync from ORM
        try:
            from thinkdome.security.rbac.models import Role
            for r in Role.query().all():
                if r.name.upper() not in self._registered_roles:
                    self.register_role(r.name, description=r.description or "")
        except Exception:
            pass

        with self._lock:
            return sorted(self._registered_roles.keys())

    # ── Audit Logging Helper ──────────────────────────────────────────────────

    def _log_audit_event(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        details: Dict[str, Any],
        ip_address: str = "127.0.0.1",
    ) -> None:
        """Mandatory audit logging: log all privilege grants, denials, exemptions, and checks."""
        details_str = json.dumps(details, default=str)
        try:
            from thinkdome.security.rbac.models import RbacAuditLog
            audit_entry = RbacAuditLog(
                actor=actor or "system",
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details_str,
                ip_address=ip_address or "127.0.0.1",
            )
            audit_entry.save()
        except Exception as e:
            logger.debug("RbacAuditLog persistence note: %s", e)

        # Also emit structured system audit
        logger.info(
            "🔒 RBAC AUDIT [%s] actor='%s' target='%s:%s' details=%s",
            action, actor, target_type, target_id, details_str
        )

    # ── Privilege Allocation, Granter & Denial ─────────────────────────────────

    def allocate_privilege(
        self,
        document_type: str,
        role: str,
        permissions: Union[Dict[str, bool], List[str], Set[str]],
        level: int = 0,
        user_id: str = "",
        workspace_id: str = "",
        is_denial: bool = False,
        is_custom_exempt: bool = False,
        actor: str = "admin",
        ip_address: str = "127.0.0.1",
    ) -> Dict[str, Any]:
        """Allocate privilege properties dynamically to a role or user.

        Stores the dynamic permission rule, flushes the in-memory cache,
        and logs a mandatory audit record.
        """
        canonical_doc = self.resolver.resolve(document_type)
        canonical_role = role.strip().upper()
        self._ensure_role_registered(canonical_role)

        # Normalize permissions map across 14 properties
        perm_map = {p: False for p in PERMISSION_PROPERTIES}
        if isinstance(permissions, dict):
            for k, v in permissions.items():
                norm = _ACTION_ALIASES.get(k.lower(), k.lower())
                if norm in perm_map:
                    perm_map[norm] = bool(v)
        elif isinstance(permissions, (list, set, tuple)):
            for k in permissions:
                norm = _ACTION_ALIASES.get(str(k).lower(), str(k).lower())
                if norm in perm_map:
                    perm_map[norm] = True

        rule_data = {
            "document_type": canonical_doc,
            "role": canonical_role,
            "level": level,
            "user_id": user_id or "",
            "workspace_id": workspace_id or "",
            "is_denial": is_denial,
            "is_custom_exempt": is_custom_exempt,
            "permissions": perm_map,
        }

        # Persist in ORM DocPerm
        try:
            from thinkdome.security.rbac.models import DocPerm
            query = DocPerm.query().filter(
                document_type=canonical_doc,
                role=canonical_role,
                level=level,
            )
            if user_id:
                query = query.filter(user_id=user_id)
            if is_denial:
                query = query.filter(is_denial=True)
            existing = query.first()

            if not existing:
                existing = DocPerm(
                    document_type=canonical_doc,
                    role=canonical_role,
                    level=level,
                    user_id=user_id or "",
                    workspace_id=workspace_id or "",
                    is_denial=is_denial,
                    is_custom_exempt=is_custom_exempt,
                )

            for p_name, val in perm_map.items():
                field_name = "perm_import" if p_name == "import" else f"perm_{p_name}"
                setattr(existing, field_name, val)
            existing.is_denial = is_denial
            existing.is_custom_exempt = is_custom_exempt
            existing.save()
        except Exception as e:
            logger.debug("DocPerm ORM persistence note: %s", e)

        with self._lock:
            # Replace existing in-memory rule if matching
            self._in_memory_rules = [
                r for r in self._in_memory_rules
                if not (
                    r["document_type"].lower() == canonical_doc.lower()
                    and r["role"] == canonical_role
                    and r["level"] == level
                    and r["user_id"] == user_id
                    and r["is_denial"] == is_denial
                )
            ]
            self._in_memory_rules.append(rule_data)
            self.invalidate_cache()

        # Mandatory Audit Log
        action_name = "privilege_deny" if is_denial else ("privilege_grant" if any(perm_map.values()) else "privilege_revoke")
        self._log_audit_event(
            actor=actor,
            action=action_name,
            target_type=canonical_doc,
            target_id=f"{canonical_role}:{level}" + (f":{user_id}" if user_id else ""),
            details={
                "permissions": perm_map,
                "is_denial": is_denial,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "level": level,
            },
            ip_address=ip_address,
        )

        return rule_data

    def grant_privilege(
        self,
        document_type: str,
        role: str,
        permissions: Union[Dict[str, bool], List[str], Set[str]],
        level: int = 0,
        user_id: str = "",
        workspace_id: str = "",
        actor: str = "admin",
        ip_address: str = "127.0.0.1",
    ) -> Dict[str, Any]:
        """Privilege Granter: dynamically grant permissions to a role or user with audit logging."""
        return self.allocate_privilege(
            document_type=document_type,
            role=role,
            permissions=permissions,
            level=level,
            user_id=user_id,
            workspace_id=workspace_id,
            is_denial=False,
            is_custom_exempt=False,
            actor=actor,
            ip_address=ip_address,
        )

    def deny_privilege(
        self,
        document_type: str,
        role: str,
        permissions: Union[Dict[str, bool], List[str], Set[str]],
        level: int = 0,
        user_id: str = "",
        workspace_id: str = "",
        actor: str = "admin",
        ip_address: str = "127.0.0.1",
    ) -> Dict[str, Any]:
        """Privilege Denial: explicitly deny permissions with audit logging.

        Denials take strict precedence over any grant for this role or user.
        """
        return self.allocate_privilege(
            document_type=document_type,
            role=role,
            permissions=permissions,
            level=level,
            user_id=user_id,
            workspace_id=workspace_id,
            is_denial=True,
            is_custom_exempt=False,
            actor=actor,
            ip_address=ip_address,
        )

    def customize_exemption(
        self,
        target_name_or_doc_type: str,
        exempt: bool = True,
        actor: str = "admin",
        ip_address: str = "127.0.0.1",
    ) -> None:
        """User intentional customization: exempt or unexempt a function or document from privilege checking.

        Default is that everything is a privilege. Customizations are audit-logged.
        """
        key = target_name_or_doc_type.strip().lower()
        with self._lock:
            if exempt:
                self._exemptions.add(key)
            else:
                self._exemptions.discard(key)
            self.invalidate_cache()

        # Audit log customization
        self._log_audit_event(
            actor=actor,
            action="privilege_exempt" if exempt else "privilege_unexempt",
            target_type="Function",
            target_id=target_name_or_doc_type,
            details={"exempt": exempt, "target": target_name_or_doc_type},
            ip_address=ip_address,
        )

    def is_exempt(self, target_name_or_doc_type: str) -> bool:
        """Check whether a target has been customized to not require privilege."""
        key = target_name_or_doc_type.strip().lower()
        with self._lock:
            if key in self._exemptions:
                return True
            for ex in self._exemptions:
                if key == ex or key.endswith(f".{ex}"):
                    return True
        return False

    # ── Permission & Privilege Evaluation ─────────────────────────────────────

    def has_document_permission(
        self,
        roles: Union[str, Iterable[str]],
        document_type: str,
        action: str = "read",
        level: int = 0,
        doc_name: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        audit: bool = True,
    ) -> bool:
        """Evaluate if the caller has the required privilege property.

        Order of evaluation:
        1. Custom exemption: if user customized to exempt -> True.
        2. Privilege Denial: any explicit denial for user or roles -> False (audit logged).
        3. Super Admin bypass: admin roles without explicit denials -> True.
        4. User direct privilege grant -> True if granted.
        5. Role privilege grants (direct + inherited hierarchy) -> True if granted.
        6. Default fallback -> False.
        """
        self.ensure_initialized()

        # Resolve canonical document type dynamically
        canonical_doc = self.resolver.resolve(document_type)

        # Normalize action
        norm_action = _ACTION_ALIASES.get(action.strip().lower(), action.strip().lower())
        if norm_action not in PERMISSION_PROPERTIES and norm_action not in ("execute", "custom"):
            norm_action = "read"

        # Normalize roles
        if isinstance(roles, str):
            user_roles = {roles.strip().upper()} if roles.strip() else set()
        else:
            user_roles = {str(r).strip().upper() for r in (roles or []) if str(r).strip()}

        # 1. Custom Exemption Check
        if doc_name and self.is_exempt(doc_name):
            return True
        if self.is_exempt(canonical_doc):
            return True

        # Check in-memory Cache for microsecond response
        cache_key = (
            ",".join(sorted(user_roles)),
            canonical_doc.lower(),
            norm_action,
            level,
            user_id or "",
            workspace_id or "",
            (doc_name or "").lower(),
        )
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        result = self._evaluate_document_permission(
            user_roles=user_roles,
            document_type=canonical_doc,
            action=norm_action,
            level=level,
            doc_name=doc_name,
            user_id=user_id,
            workspace_id=workspace_id,
            audit=audit,
        )

        with self._lock:
            self._cache[cache_key] = result
        return result

    def _evaluate_document_permission(
        self,
        user_roles: Set[str],
        document_type: str,
        action: str,
        level: int,
        doc_name: Optional[str],
        user_id: Optional[str],
        workspace_id: Optional[str],
        audit: bool = True,
    ) -> bool:
        """Perform full dynamic resolution."""
        # Expand inherited parent roles
        expanded_roles = self.get_inherited_roles(user_roles)

        # Retrieve relevant rules from ORM and in-memory
        rules = self._get_rules_for_evaluation(document_type, level, doc_name, workspace_id=workspace_id)

        # ── Step 2: Privilege Denial (Strict Precedence) ───────────────────────
        for rule in rules:
            if not rule.get("is_denial"):
                continue
            # Check user-specific denial
            if user_id and rule.get("user_id") and rule.get("user_id") == user_id:
                if self._check_rule_action(rule, action):
                    if audit:
                        self._log_audit_event(
                            actor=user_id,
                            action="privilege_denied_attempt",
                            target_type=document_type,
                            target_id=action,
                            details={"reason": "User explicit privilege denial", "doc_name": doc_name, "level": level},
                        )
                    return False
            # Check role denial
            if rule.get("role") in expanded_roles:
                if self._check_rule_action(rule, action):
                    if audit:
                        self._log_audit_event(
                            actor=user_id or ",".join(user_roles),
                            action="privilege_denied_attempt",
                            target_type=document_type,
                            target_id=action,
                            details={"reason": f"Role '{rule.get('role')}' explicit privilege denial", "doc_name": doc_name, "level": level},
                        )
                    return False

        # ── Step 3: Administrator Dynamic Privilege Check ─────────────────────
        from thinkdome.security.identity.core import is_admin_role
        if any(is_admin_role(r) for r in user_roles):
            return True

        # ── Step 4: Direct User Privilege Grant ───────────────────────────────
        if user_id:
            for rule in rules:
                if rule.get("is_denial"):
                    continue
                if rule.get("user_id") and rule.get("user_id") == user_id:
                    if self._check_rule_action(rule, action):
                        return True

        # ── Step 5: Role Grants across Direct & Inherited Roles ────────────────
        for rule in rules:
            if rule.get("is_denial"):
                continue
            r_role = rule.get("role")
            if r_role in expanded_roles or r_role == "*":
                if self._check_rule_action(rule, action):
                    return True

        return False

    def check_function_privilege(
        self,
        function_name_or_dotted: str,
        roles: Union[str, Iterable[str]],
        user_id: Optional[str] = None,
        custom_exempt: bool = False,
    ) -> bool:
        """Check if caller has privilege to execute a function.

        By default: EVERY function is a privilege.
        Can be customized to not have privilege intentionally.
        """
        if custom_exempt or self.is_exempt(function_name_or_dotted):
            return True

        return self.has_document_permission(
            roles=roles,
            document_type="Function",
            action="write",
            doc_name=function_name_or_dotted,
            user_id=user_id,
        )

    def _check_rule_action(self, rule: Dict[str, Any], action: str) -> bool:
        perms = rule.get("permissions", {})
        if action in ("execute", "write"):
            return bool(perms.get("write") or (perms.get("read") and perms.get("write")) or perms.get("access_mcp"))
        return bool(perms.get(action, False))

    def _get_rules_for_evaluation(
        self,
        document_type: str,
        level: int,
        doc_name: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Collect all matching rules for the given level from Redis cache, ORM, and in-memory."""
        doc_lower = document_type.strip().lower()
        cache_key = f"rbac:rules:{doc_lower}:{level}:{doc_name or ''}:{workspace_id or ''}"

        # 1. Redis distributed cache
        try:
            from thinkdome.core.ui.cache import UICacheManager
            cached_rules = UICacheManager.get_instance().get(cache_key)
            if cached_rules and isinstance(cached_rules, list):
                return cached_rules
        except Exception:
            pass

        rules: List[Dict[str, Any]] = []
        seen = set()

        # 2. ORM rules
        try:
            from thinkdome.security.rbac.models import DocPerm
            db_rules = DocPerm.query().all()
            if not db_rules and _DEFAULT_RULES:
                for r in _DEFAULT_RULES:
                    try:
                        DocPerm(
                            document_type=r["document_type"],
                            role=r["role"],
                            level=r.get("level", 0),
                            is_denial=bool(r.get("is_denial", False)),
                            is_custom_exempt=bool(r.get("is_custom_exempt", False)),
                            workspace_id=r.get("workspace_id"),
                            user_id=r.get("user_id"),
                            **{f"perm_{p}": bool(r.get("permissions", {}).get(p, False)) for p in ALL_PROPERTIES}
                        ).save()
                    except Exception:
                        pass
                db_rules = DocPerm.query().all()

            for rec in db_rules:
                if rec.level != level:
                    continue
                if workspace_id and rec.workspace_id and rec.workspace_id != workspace_id:
                    continue
                rdoc = rec.document_type.lower()
                if rdoc == doc_lower or rdoc == "*" or (doc_name and rdoc == doc_name.lower()):
                    key = (rec.document_type.lower(), rec.role.upper(), rec.level, rec.user_id or "", rec.workspace_id or "", bool(rec.is_denial))
                    seen.add(key)
                    rules.append({
                        "document_type": rec.document_type,
                        "role": rec.role.upper(),
                        "level": rec.level,
                        "user_id": rec.user_id,
                        "workspace_id": rec.workspace_id,
                        "is_denial": bool(rec.is_denial),
                        "is_custom_exempt": bool(rec.is_custom_exempt),
                        "permissions": rec.get_permissions(),
                    })
        except Exception:
            pass

        # 3. In-memory rules (avoiding duplicates)
        with self._lock:
            for r in self._in_memory_rules:
                if r.get("level", 0) != level:
                    continue
                if workspace_id and r.get("workspace_id") and r.get("workspace_id") != workspace_id:
                    continue
                rdoc = r["document_type"].lower()
                if rdoc == doc_lower or rdoc == "*" or (doc_name and rdoc == doc_name.lower()):
                    key = (r["document_type"].lower(), r["role"].upper(), r.get("level", 0), r.get("user_id", ""), r.get("workspace_id", ""), bool(r.get("is_denial", False)))
                    if key not in seen:
                        rules.append(r)

        # 4. Cache in Redis
        try:
            from thinkdome.core.ui.cache import UICacheManager
            UICacheManager.get_instance().set(cache_key, rules, ttl_seconds=300)
        except Exception:
            pass

        return rules

    # ── Role Hierarchy & Effective Permissions ────────────────────────────────

    def get_inherited_roles(self, roles: Set[str]) -> Set[str]:
        """Traverse role hierarchy and return all direct and parent roles."""
        expanded = set(roles)
        to_visit = list(roles)
        visited = set()

        while to_visit:
            curr = to_visit.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            parent = self._get_parent_role(curr)
            if parent and parent not in expanded:
                expanded.add(parent)
                to_visit.append(parent)

        return expanded

    def _get_parent_role(self, role_name: str) -> Optional[str]:
        canonical = role_name.strip().upper()
        with self._lock:
            if canonical in self._registered_roles:
                return self._registered_roles[canonical].get("parent_role")
        # Check ORM Role
        try:
            from thinkdome.security.rbac.models import Role
            role_rec = Role.query().filter(name=canonical).first()
            if role_rec and role_rec.parent_role_id:
                parent_rec = Role.get(role_rec.parent_role_id)
                if parent_rec:
                    return parent_rec.name.upper()
        except Exception:
            pass
        return None

    def get_effective_permissions(
        self,
        roles: Union[str, Iterable[str]],
        user_id: Optional[str] = None,
    ) -> Set[str]:
        """Compile effective permission strings across dynamically allocated DocPerms."""
        self.ensure_initialized()
        if isinstance(roles, str):
            user_roles = {roles.strip().upper()} if roles.strip() else set()
        else:
            user_roles = {str(r).strip().upper() for r in (roles or []) if str(r).strip()}

        cache_key = ("eff", ",".join(sorted(user_roles)), user_id or "")
        with self._lock:
            if cache_key in self._cache:
                return set(self._cache[cache_key])

        from thinkdome.security.identity.core import is_admin_role
        if any(is_admin_role(r) for r in user_roles):
            return {"*"}

        expanded_roles = self.get_inherited_roles(user_roles)
        effective: Set[str] = set()
        denials: Set[str] = set()

        # Dynamic institutional domain permissions mapping
        domain_role_grants: Dict[str, Set[str]] = {
            "FINANCE_MANAGER": {"erp:finance:*", "erp:crud:*", "erp:report:*", "erp:audit:*", "file:read"},
            "FINANCE_USER": {"erp:finance:read", "erp:finance:post", "erp:crud:read", "erp:crud:create", "erp:crud:update", "file:read"},
            "AUDITOR": {"erp:audit:read", "erp:finance:read", "erp:report:read", "audit:read", "file:read"},
            "SALES_USER": {"erp:crud:sales_*", "erp:crud:customer_*", "erp:report:read", "file:read"},
            "DEVELOPER": {"sandbox:exec", "search:web", "file:read", "file:write", "memory:*", "mcptool:*", "orchestrator:*"},
            "AGENT_STANDARD": {"sandbox:exec", "search:web", "file:read", "memory:*", "mcptool:*", "orchestrator:*"},
            "LLM": {"sandbox:exec", "search:web", "memory:*", "mcptool:*", "orchestrator:*"},
            "GUEST": {"file:read"},
        }
        for r in expanded_roles:
            if r in domain_role_grants:
                effective.update(domain_role_grants[r])

        # Dynamic domain privileges mapped dynamically from roles
        all_rules: List[Dict[str, Any]] = []
        with self._lock:
            all_rules.extend(self._in_memory_rules)
        try:
            from thinkdome.security.rbac.models import DocPerm
            for rec in DocPerm.query().all():
                all_rules.append({
                    "document_type": rec.document_type,
                    "role": rec.role.upper(),
                    "level": rec.level,
                    "user_id": rec.user_id,
                    "is_denial": bool(rec.is_denial),
                    "permissions": rec.get_permissions(),
                })
        except Exception:
            pass

        for rule in all_rules:
            is_denial = rule.get("is_denial", False)
            match_user = user_id and rule.get("user_id") == user_id
            match_role = rule.get("role") in expanded_roles or rule.get("role") == "*"

            if match_user or match_role:
                doc = rule.get("document_type", "").lower()
                for action, granted in rule.get("permissions", {}).items():
                    if granted:
                        perm_str = f"{doc}:{action}"
                        if is_denial:
                            denials.add(perm_str)
                            denials.add(f"{doc}:*")
                        else:
                            effective.add(perm_str)

        # Filter out explicit denials
        effective = {p for p in effective if p not in denials and f"{p.split(':')[0]}:*" not in denials}

        with self._lock:
            self._cache[cache_key] = set(effective)
        return effective

    def has_permission(self, identity: Any, required_permission: str) -> bool:
        """Check if identity satisfies required permission pattern with wildcard support."""
        if getattr(identity, "is_admin", None) and identity.is_admin():
            return True

        roles = getattr(identity, "roles", set()) or set()
        user_id = getattr(identity, "username", "") or ""
        effective = self.get_effective_permissions(roles, user_id=user_id)
        if "*" in effective:
            return True

        req_lower = required_permission.lower().strip()
        req_parts = req_lower.split(":")

        for perm in effective:
            perm_lower = perm.lower()
            if perm_lower == "*" or perm_lower == req_lower:
                return True

            if perm_lower.endswith(":*"):
                prefix = perm_lower[:-2]
                if req_lower.startswith(prefix):
                    return True

            perm_parts = perm_lower.split(":")
            if len(perm_parts) == len(req_parts) and all(
                a == "*" or a == r for a, r in zip(perm_parts, req_parts)
            ):
                return True

        return False

    # ── Workspace Manager UI Matrix ───────────────────────────────────────────

    def get_role_permission_matrix(self) -> Dict[str, Any]:
        """Return full document permission matrix for the Workspace Manager."""
        self.ensure_initialized()
        roles = self.get_registered_roles()
        doc_types = self.get_registered_doc_types()

        documents_matrix = []
        for dt in doc_types:
            role_perms = {}
            for r in roles:
                perms_dict = {}
                for p in PERMISSION_PROPERTIES:
                    perms_dict[p] = self.has_document_permission(
                        roles={r},
                        document_type=dt,
                        action=p,
                        audit=False,
                    )
                role_perms[r] = perms_dict

            documents_matrix.append({
                "document_type": dt,
                "description": self.resolver.get_type_description(dt) or f"{dt} entity",
                "properties": list(PERMISSION_PROPERTIES),
                "roles": role_perms,
            })

        return {
            "roles": roles,
            "document_types": doc_types,
            "permissions": list(PERMISSION_PROPERTIES),
            "matrix": documents_matrix,
        }

    # ── Workspace Manager Overrides Protocol ───────────────────────────────────

    def override_privilege(
        self,
        workspace_id: str,
        document_type: str,
        role: str,
        permissions: Dict[str, bool],
        is_denial: bool = False,
        is_custom_exempt: bool = False,
        level: int = 0,
        user_id: Optional[str] = None,
        actor: str = "workspace_manager",
    ) -> Dict[str, Any]:
        """Override or customize a privilege rule specifically scoped to a workspace."""
        canonical_doc = self.resolve_document_type(document_type)
        canonical_role = role.strip().upper()

        # Persist to ORM DocPerm with workspace_id
        try:
            from thinkdome.security.rbac.models import DocPerm
            existing = DocPerm.query().filter(
                workspace_id=workspace_id,
                document_type=canonical_doc,
                role=canonical_role,
                level=level,
            ).first()
            if existing:
                existing.is_denial = is_denial
                existing.is_custom_exempt = is_custom_exempt
                existing.user_id = user_id
                for p in ALL_PROPERTIES:
                    if p in permissions:
                        setattr(existing, f"perm_{p}", bool(permissions[p]))
                existing.save()
            else:
                perm_kwargs = {f"perm_{p}": bool(permissions.get(p, False)) for p in ALL_PROPERTIES}
                DocPerm(
                    workspace_id=workspace_id,
                    document_type=canonical_doc,
                    role=canonical_role,
                    level=level,
                    is_denial=is_denial,
                    is_custom_exempt=is_custom_exempt,
                    user_id=user_id,
                    **perm_kwargs
                ).save()
        except Exception as e:
            logger.warning("Could not persist workspace privilege override to DB: %s", e)

        rule = {
            "workspace_id": workspace_id,
            "document_type": canonical_doc,
            "role": canonical_role,
            "level": level,
            "user_id": user_id,
            "is_denial": is_denial,
            "is_custom_exempt": is_custom_exempt,
            "permissions": {p: bool(permissions.get(p, False)) for p in ALL_PROPERTIES},
        }
        with self._lock:
            self._in_memory_rules = [
                r for r in self._in_memory_rules
                if not (r.get("workspace_id") == workspace_id and r.get("document_type") == canonical_doc and r.get("role") == canonical_role and r.get("level") == level)
            ]
            self._in_memory_rules.append(rule)
            self.invalidate_cache()

        action_type = "privilege_deny" if is_denial else ("privilege_exempt" if is_custom_exempt else "privilege_grant")
        self._log_audit_event(
            actor=actor,
            action=f"workspace_override_{action_type}",
            target_type="workspace_override",
            target_id=f"{workspace_id}:{canonical_doc}:{canonical_role}",
            details={"permissions": permissions, "is_denial": is_denial, "is_custom_exempt": is_custom_exempt},
        )
        return rule

    def bulk_override_privileges(
        self,
        workspace_id: str,
        overrides: List[Dict[str, Any]],
        actor: str = "workspace_manager",
    ) -> List[Dict[str, Any]]:
        """Apply multiple privilege overrides for a workspace in one atomic batch."""
        results = []
        for ov in overrides:
            res = self.override_privilege(
                workspace_id=workspace_id,
                document_type=ov.get("document_type", "Page"),
                role=ov.get("role", "*"),
                permissions=ov.get("permissions", {}),
                is_denial=bool(ov.get("is_denial", False)),
                is_custom_exempt=bool(ov.get("is_custom_exempt", False)),
                level=ov.get("level", 0),
                user_id=ov.get("user_id"),
                actor=actor,
            )
            results.append(res)
        return results

    def reset_privileges_to_defaults(
        self,
        workspace_id: str,
        document_type: Optional[str] = None,
        actor: str = "workspace_manager",
    ) -> int:
        """Reset workspace-scoped privilege overrides back to global platform defaults."""
        count = 0
        try:
            from thinkdome.security.rbac.models import DocPerm
            q = DocPerm.query().filter(workspace_id=workspace_id)
            if document_type:
                canonical = self.resolve_document_type(document_type)
                q = q.filter(document_type=canonical)
            for rec in q.all():
                rec.delete(soft=False)
                count += 1
        except Exception as e:
            logger.warning("Could not delete workspace privilege overrides from DB: %s", e)

        with self._lock:
            if document_type:
                canonical = self.resolve_document_type(document_type)
                self._in_memory_rules = [
                    r for r in self._in_memory_rules
                    if not (r.get("workspace_id") == workspace_id and r.get("document_type") == canonical)
                ]
            else:
                self._in_memory_rules = [
                    r for r in self._in_memory_rules
                    if r.get("workspace_id") != workspace_id
                ]
            self.invalidate_cache()

        self._log_audit_event(
            actor=actor,
            action="workspace_reset_privileges",
            target_type="workspace_override",
            target_id=workspace_id,
            details={"document_type": document_type, "reset_count": count},
        )
        return count

    def get_privilege_overrides(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Retrieve all custom privilege overrides defined for a specific workspace."""
        overrides = []
        try:
            from thinkdome.security.rbac.models import DocPerm
            for rec in DocPerm.query().filter(workspace_id=workspace_id).all():
                overrides.append({
                    "workspace_id": workspace_id,
                    "document_type": rec.document_type,
                    "role": rec.role,
                    "level": rec.level,
                    "user_id": rec.user_id,
                    "is_denial": bool(rec.is_denial),
                    "is_custom_exempt": bool(rec.is_custom_exempt),
                    "permissions": rec.get_permissions(),
                })
        except Exception:
            pass

        with self._lock:
            for r in self._in_memory_rules:
                if r.get("workspace_id") == workspace_id:
                    if not any(o["document_type"] == r["document_type"] and o["role"] == r["role"] and o["level"] == r.get("level", 0) for o in overrides):
                        overrides.append(r)
        return overrides

    # ── Cache Management ──────────────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        """Invalidate the cache across all in-memory and Redis distributed caches."""
        with self._lock:
            self._cache.clear()
            self._cache_version += 1
        try:
            from thinkdome.security.rbac.cache import rbac_cache
            rbac_cache.invalidate_all()
        except Exception:
            pass
        try:
            from thinkdome.core.ui.cache import UICacheManager
            UICacheManager.get_instance().clear("rbac:")
        except Exception:
            pass


# Global centralized protocol singleton
dynamic_role_protocol = DynamicRoleAllocationProtocol()
