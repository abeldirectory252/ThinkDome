"""ThinkDome Tool Registration Framework.

Exposes decorators and dynamic registries to register, structure, and inspect
tools dynamically from the core and installed apps.
"""

from __future__ import annotations

import inspect
import logging
import contextvars
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any, Optional, Dict, List

logger = logging.getLogger(__name__)

# Context variable for the currently executing tool
current_tool_context: contextvars.ContextVar[Optional[ToolContext]] = contextvars.ContextVar(
    "current_tool_context", default=None
)


@dataclass
class ToolContext:
    """Carries the execution pipeline, active workspace path, sandbox limits, and enterprise identity."""

    username: str
    sandbox_id: Optional[str]
    workspace_dir: Path
    execution_service: Any
    search_service: Any
    db: Any
    caller_role: str
    sandbox_limits: Optional[dict] = None
    credential_vault: Any = None
    security_scanner: Any = None
    services: Dict[str, Any] = field(default_factory=dict)
    identity: Optional[Any] = None

    def get_identity(self) -> Any:
        """Retrieve strongly-typed UserIdentity, building dynamically if not set."""
        if self.identity is not None:
            return self.identity
        from thinkdome.security.identity.core import UserIdentity
        return UserIdentity.from_dict({
            "username": self.username,
            "caller_role": self.caller_role,
        })

    def get_service(self, name: str) -> Optional[Any]:
        """Retrieve a contextually bound service instance."""
        return self.services.get(name)

    def set_service(self, name: str, service: Any) -> None:
        """Register a contextual service instance."""
        self.services[name] = service

    async def execute_code(self, code: str, language: str = "python") -> dict:
        """Execute a code block inside the sandbox execution pipeline."""
        from thinkdome.execution.core.models import ExecuteRequest

        # Enforce sandbox timeout if present
        timeout_ms = 5000
        if self.sandbox_limits and "timeout_sec" in self.sandbox_limits:
            timeout_ms = self.sandbox_limits["timeout_sec"] * 1000

        # Enforce sandbox network enablement if present
        allow_network = False
        if self.sandbox_limits and "network_enabled" in self.sandbox_limits:
            allow_network = bool(self.sandbox_limits["network_enabled"])

        exec_req = ExecuteRequest(
            code=code,
            language=language,
            stdin=None,
            security_profile="HIGH_SECURITY",
            env_vars={},
            caller_role=self.caller_role,
            allow_network=allow_network,
            memory_limit_mb=self.sandbox_limits.get("memory_mb") if self.sandbox_limits else None,
            cpu_cores=self.sandbox_limits.get("cpu_cores") if self.sandbox_limits else None,
            timeout_ms=timeout_ms,
            username=self.username,
        )
        
        resp = await self.execution_service.execute(exec_req)
        return {
            "stdout": resp.stdout,
            "stderr": resp.stderr,
            "exit_code": resp.exit_code,
            "timed_out": resp.timed_out,
            "duration_ms": resp.duration_ms,
        }


def get_context() -> ToolContext:
    """Retrieve the current tool context from thread-local / context-local storage."""
    ctx = current_tool_context.get()
    if ctx is None:
        raise RuntimeError("No active tool context is available. Tools must be executed via OrchestratorService.")
    return ctx


class RegisteredTool:
    """Wraps a registered tool function/method along with its metadata and schema."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable,
        required_scope: Optional[str] = None,
        input_schema: Optional[Any] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ):
        self.name = name
        self.description = description
        self.func = func
        self.required_scope = required_scope or f"tool:{name}"
        self.app_name = self._determine_app(func)
        self.category = category or "general"
        self.tags = tags or []

        if input_schema is not None:
            if hasattr(input_schema, "model_json_schema"):
                self.input_schema = input_schema.model_json_schema()
            else:
                self.input_schema = input_schema
        else:
            self.input_schema = self._generate_schema(func)

    def _determine_app(self, func: Callable) -> str:
        """Identify which framework application this tool belongs to."""
        module_name = func.__module__
        if module_name.startswith("thinkdome.apps."):
            parts = module_name.split(".")
            if len(parts) >= 3:
                return parts[2]
        return "core"

    def _generate_schema(self, func: Callable) -> dict:
        """Examine function parameters dynamically to compile JSON Schema representation."""
        sig = inspect.signature(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            # Skip framework-injected parameters
            if name in ("self", "cls", "context"):
                continue

            param_type = param.annotation
            type_str = "string"
            
            if param_type is int:
                type_str = "integer"
            elif param_type is float:
                type_str = "number"
            elif param_type is bool:
                type_str = "boolean"
            elif param_type is list:
                type_str = "array"
            elif param_type is dict:
                type_str = "object"

            properties[name] = {
                "type": type_str,
                "description": f"Parameter '{name}'"
            }

            if param.default == inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


from abc import ABC, abstractmethod
from dataclasses import field
from pydantic import BaseModel
from typing import Type

class BaseTool(ABC):
    """Abstract base class representing a framework tool."""
    name: str
    description: str
    required_scope: str
    input_schema: Optional[Type[BaseModel]] = None
    category: Optional[str] = "general"
    tags: Optional[list[str]] = None

    @abstractmethod
    async def execute(self, tool_input: dict[str, Any]) -> str:
        """Execution logic for the tool."""
        pass


class ToolRegistry:
    """Central manager maintaining registry lists of framework tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        description: str,
        required_scope: Optional[str] = None,
        input_schema: Optional[dict] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Callable:
        """Register a function as a dynamic tool."""
        def decorator(func: Callable) -> Callable:
            tool = RegisteredTool(
                name=name,
                description=description,
                func=func,
                required_scope=required_scope,
                input_schema=input_schema,
                category=category,
                tags=tags,
            )
            self._tools[name] = tool
            return func
        return decorator

    def register_tool_instance(self, tool: BaseTool) -> None:
        """Register a BaseTool instance dynamically."""
        registered = RegisteredTool(
            name=tool.name,
            description=tool.description,
            func=tool.execute,
            required_scope=tool.required_scope,
            input_schema=tool.input_schema,
            category=getattr(tool, "category", "general"),
            tags=getattr(tool, "tags", []),
        )
        self._tools[tool.name] = registered

    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """Fetch a registered tool by its name."""
        return self._tools.get(name)

    def list_all_tools(self) -> list[RegisteredTool]:
        """Retrieve all tools currently loaded in the registry."""
        return list(self._tools.values())

    def get_active_tools(
        self,
        site_name: str = "personal",
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[RegisteredTool]:
        """Filter registered tools to return only those belonging to active apps, with optional category/search filters."""
        from thinkdome.core.kernel.kernel import Kernel

        # Safely fetch active apps from the kernel config context
        try:
            kernel = Kernel.get_instance(site_name)
            if not kernel.initialized:
                kernel.initialize()
            active_apps = set(kernel.get_installed_apps())
        except Exception as e:
            logger.warning(f"Failed to fetch active apps from kernel: {e}. Returning all core tools.")
            active_apps = set()

        active_tools = []
        for tool in self._tools.values():
            if active_apps and tool.app_name != "core" and tool.app_name not in active_apps:
                continue

            # Category filter
            if category and tool.category.lower() != category.lower():
                continue

            # Search term filter
            if search:
                term = search.lower()
                if term not in tool.name.lower() and term not in tool.description.lower():
                    continue

            active_tools.append(tool)
        return active_tools


# Global singleton instances
registry = ToolRegistry()
think_tool = registry.register
think_tools = registry.register  # alias

def register_tool(cls: Type[BaseTool]) -> Type[BaseTool]:
    """Decorator to register a BaseTool class instance dynamically."""
    instance = cls()
    registry.register_tool_instance(instance)
    return cls

# Import core tools to trigger class-based registration
import thinkdome.storage.tools.storage_tools
import thinkdome.execution.tools.execution_tools
import thinkdome.orchestration.search.tools
import thinkdome.orchestration.memory.tools
import thinkdome.orchestration.comms.tools
import thinkdome.orchestration.network.tools
import thinkdome.apps.erp.tools
