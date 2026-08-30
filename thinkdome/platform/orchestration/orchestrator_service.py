import contextvars
import os
import json
import logging
import inspect
from pathlib import Path
from typing import Any, Optional, Callable, Awaitable

from thinkdome.core.config import Settings
from thinkdome.sandbox.core.service import ExecutionService
from thinkdome.platform.orchestration.search.service import SearchService
from thinkdome.sandbox.core.models import ExecuteRequest
from thinkdome.platform.orchestration.search.models import SearchRequest

# Dynamic tools registration and schema imports
from thinkdome.platform.orchestration.tools import registry, ToolContext, current_tool_context
from thinkdome.platform.orchestration.hooks import (
    ExecutionContext, ExecutionHookManager, HookRegistration,
    ExecutionHookTimeout, freeze_execution_value,
)

logger = logging.getLogger(__name__)


def _bounded_log_input(value: Any) -> Any:
    """Keep tool telemetry bounded without persisting caller-controlled payloads."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower().replace("-", "_")
                   for part in ("password", "secret", "token", "api_key", "authorization", "credential")):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _bounded_log_input(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_log_input(v) for v in value[:100]]
    if isinstance(value, str):
        return value if len(value) <= 512 else value[:512] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"

# Context variable to hold username for current execution thread/task
current_username: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_username", default=None)


class _CallableHookAdapter:
    """Compatibility adapter for legacy callback hooks."""

    def __init__(self, callback: Callable[..., Any], *, before: bool = True, after: bool = True) -> None:
        self.callback = callback
        self.before = before
        self.after = after

    async def before_execute(self, context: ExecutionContext) -> None:
        if not self.before:
            return
        result = self.callback(**context.__dict__)
        if inspect.isawaitable(result):
            await result

    async def after_execute(self, context: ExecutionContext, result: dict) -> None:
        if not self.after:
            return
        callback = self.callback
        if callback is None:
            return
        value = callback(**context.__dict__, result=result)
        if inspect.isawaitable(value):
            await value

# ── Role-Based Access Control (RBAC) Scopes Matrix ──
ROLE_SCOPES = {
    "LLM": {"code:run", "memory:read", "memory:write", "web:host"},
    "WEB": {
        "code:run", "file:read", "file:write", "web:host",
        "memory:read", "memory:write"
    },
    "SDK": {
        "code:run", "file:read", "file:write", "web:host",
        "web:search", "memory:read", "memory:write"
    },
    "CURL": {
        "code:run", "file:read", "file:write", "web:host",
        "web:search", "memory:read", "memory:write"
    },
    "ORCH": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "web:host", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "admin:all"
    },
    "IDE": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "web:host", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "pty:all"
    },
    "ADMIN": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "web:host", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "pty:all", "admin:all"
    }
}

# Administrative roles inherit the complete ADMIN tool scope.  Without these
# aliases, a correctly authenticated SUPER_ADMIN fell through to the LLM
# default because it was absent from the matrix.
ROLE_SCOPES["SUPER_ADMIN"] = ROLE_SCOPES["ADMIN"]
ROLE_SCOPES["ENTERPRISE_ADMIN"] = ROLE_SCOPES["ADMIN"]
ROLE_SCOPES["ORCHESTRATOR"] = ROLE_SCOPES["ORCH"]


class OrchestratorService:
    """Validates and executes tool use blocks like an LLM orchestrator."""

    def __init__(
        self,
        settings: Settings,
        execution_service: ExecutionService,
        search_service: SearchService,
        security_scanner = None,
        credential_vault = None,
        before_execute_hooks: Optional[list[Callable[..., Any]]] = None,
        after_execute_hooks: Optional[list[Callable[..., Any]]] = None,
    ) -> None:
        self.settings = settings
        self.execution_service = execution_service
        self.search_service = search_service
        self.security_scanner = security_scanner
        self.credential_vault = credential_vault
        self.db = None
        self.hooks = ExecutionHookManager(timeout_seconds=settings.EXECUTION_HOOK_TIMEOUT_MS / 1000)
        self.before_execute_hooks = list(before_execute_hooks or [])  # compatibility facade
        self.after_execute_hooks = list(after_execute_hooks or [])  # compatibility facade
        self.before_execute_audit_hook: Optional[Callable[..., Any]] = self._default_before_execute_audit
        self.hooks.set_audit_hook(_CallableHookAdapter(self.before_execute_audit_hook, after=False))
        for callback in self.before_execute_hooks:
            self.hooks.register(_CallableHookAdapter(callback, after=False), priority=100)
        for callback in self.after_execute_hooks:
            self.hooks.register(_CallableHookAdapter(callback, before=False), priority=100)
        
        # Set workspace root to the project root directory
        self.workspace_root = Path(__file__).resolve().parents[3]
        logger.info(f"OrchestratorService initialized with workspace root: {self.workspace_root}")

    def add_sandbox_hooks(
        self,
        before_execute: Optional[Callable[..., Any]] = None,
        after_execute: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Register lifecycle hooks shared by MCP and orchestrated execution."""
        if before_execute is not None:
            self.before_execute_hooks.append(before_execute)
            self.hooks.register(_CallableHookAdapter(before_execute, after=False), priority=100)
        if after_execute is not None:
            self.after_execute_hooks.append(after_execute)
            self.hooks.register(_CallableHookAdapter(after_execute, before=False), priority=100)

    def set_before_execute_audit_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """Replace the default execution-intent audit hook (pass None to disable)."""
        self.before_execute_audit_hook = hook
        self.hooks.set_audit_hook(_CallableHookAdapter(hook, after=False) if hook is not None else None)

    def register_execution_hook(self, hook: Any, *, priority: int = 100) -> HookRegistration:
        """Register a typed ExecutionHook; lower priorities run first."""
        return self.hooks.register(hook, priority=priority)

    def unregister_execution_hook(self, registration: HookRegistration) -> bool:
        """Remove a previously registered hook without disturbing other plugins."""
        return self.hooks.unregister(registration)

    def _default_before_execute_audit(self, **payload: Any) -> None:
        """Record an execution intent before invoking any privileged tool."""
        tool_use = payload.get("tool_use") or {}
        details = {
            "tool_name": tool_use.get("name", "unknown"),
            "input": _bounded_log_input(tool_use.get("input", {})),
            "sandbox_id": payload.get("sandbox_id"),
            "caller_role": payload.get("caller_role"),
        }
        if self.db is not None and hasattr(self.db, "log_audit"):
            self.db.log_audit(
                actor=str(payload.get("username") or "anonymous"),
                action="sandbox_execution_intent",
                ip_address="orchestrator",
                details=details,
            )
        else:
            logger.info("sandbox_execution_intent: %s", details)

    async def _run_sandbox_hooks(self, hooks: list[Callable[..., Any]], **payload: Any) -> None:
        for hook in tuple(hooks):
            result = hook(**payload)
            if inspect.isawaitable(result):
                await result

    def validate_request(self, data: dict) -> None:
        """Validate request against Pydantic Python schema."""
        from thinkdome.platform.orchestration.orchestrator_models import ToolUseRequest
        from pydantic import ValidationError

        try:
            req = ToolUseRequest.model_validate(data)
            req.validate_input()
        except ValidationError as e:
            error_msgs = []
            for err in e.errors():
                loc = " -> ".join(str(l) for l in err.get("loc", []))
                msg = err.get("msg", "Invalid value")
                error_msgs.append(f"{loc}: {msg}" if loc else msg)
            raise ValueError(f"Validation failed: {'; '.join(error_msgs)}")
        except Exception as e:
            raise ValueError(str(e))

    def get_user_workspace(self, username: Optional[str]) -> Path:
        """Get the user-specific workspace root directory on the host."""
        import hashlib
        raw_user = (username or "anonymous").strip().lower()
        # Hash username to a clean 32-char hex string namespace to prevent directory escape
        namespace = hashlib.sha256(raw_user.encode("utf-8")).hexdigest()[:32]
        base_dir = Path(self.settings.FILE_STORAGE_DIR).resolve() / "workspaces"
        user_dir = (base_dir / namespace).resolve()
        try:
            user_dir.relative_to(base_dir)
        except ValueError:
            user_dir = base_dir / "anonymous"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _resolve_safe_path(self, path_str: str) -> Path:
        """Resolve path and ensure it remains within the user-specific workspace directory."""
        # Clean leading slashes and drive letters
        cleaned = path_str.lstrip("/\\")
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].lstrip("/\\")
        
        workspace_root = self.get_user_workspace(current_username.get()).resolve()
        target_path = Path(os.path.abspath(workspace_root / cleaned)).resolve()
        try:
            target_path.relative_to(workspace_root)
        except ValueError:
            raise PermissionError(f"Access denied: path '{path_str}' escapes workspace boundaries.")
        return target_path

    async def execute_tool(self, tool_use: dict, caller_role: str = "LLM", sandbox_limits: Optional[dict] = None, username: Optional[str] = None, sandbox_id: Optional[str] = None) -> dict:
        """Execute a tool use request and return a tool result block."""
        token = current_username.set(username)

        # Set up dynamic ToolContext
        user_workspace = self.get_user_workspace(username)
        tool_ctx = ToolContext(
            username=username or "anonymous",
            sandbox_id=sandbox_id,
            workspace_dir=user_workspace,
            execution_service=self.execution_service,
            search_service=self.search_service,
            db=None,
            caller_role=caller_role,
            sandbox_limits=sandbox_limits,
            credential_vault=self.credential_vault,
            security_scanner=self.security_scanner,
        )

        from thinkdome.core.kernel.kernel import Kernel
        try:
            kernel = Kernel.current()
            if kernel.initialized and kernel.db:
                tool_ctx.db = kernel.db
        except Exception:
            pass

        ctx_token = current_tool_context.set(tool_ctx)
        try:
            tool_id = tool_use["id"]
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            execution_context = ExecutionContext(
                tool_use=freeze_execution_value(tool_use),
                sandbox_id=sandbox_id,
                username=username or "anonymous",
                caller_role=caller_role,
            )

            logger.info("Executing tool %s (id: %s) with input summary %s (caller: %s)",
                        tool_name, tool_id, _bounded_log_input(tool_input), caller_role)
            
            try:
                # Retrieve the tool from our dynamic registry
                tool = registry.get_tool(tool_name)
                if not tool:
                    raise ValueError(f"Unknown tool name: {tool_name}")

                # Apply persisted MCP policy at the execution boundary too;
                # listing filters alone are not authorization.
                from thinkdome.core.ui.service import UIManager
                from thinkdome.security.identity.core import is_admin_role
                policy = UIManager().get_mcp_tool_metadata().get(tool_name)
                role_upper = (caller_role or "LLM").upper()
                if policy and not policy.get("is_active", True):
                    raise PermissionError(f"Access denied: MCP tool '{tool_name}' is inactive.")
                if policy and policy.get("allowed_roles") and not is_admin_role(role_upper):
                    allowed_roles = {str(value).upper() for value in policy["allowed_roles"]}
                    if role_upper not in allowed_roles:
                        raise PermissionError(f"Access denied: MCP tool '{tool_name}' is not allowed for role '{caller_role}'.")

                # Ensure non-core (app) tools are active in the current site config
                if tool.app_name != "core":
                    site_name = os.environ.get("THINKDOME_SITE", "think.local")
                    active_tools = registry.get_active_tools(site_name)
                    active_names = {t.name for t in active_tools}
                    if tool_name not in active_names:
                        raise PermissionError(
                            f"Access denied: Tool '{tool_name}' is inactive/disabled for the current site context."
                        )

                # ── PRIVILEGE VERIFICATION ──
                required_scope = tool.required_scope
                
                # Fetch scopes allowed for this role
                allowed_scopes = ROLE_SCOPES.get(role_upper, ROLE_SCOPES["LLM"])
                
                # Verify required scope is in caller's allowed scopes
                if required_scope and required_scope not in allowed_scopes:
                    ADMIN_ONLY_TOOLS = {
                        "write_file", "make_dir", "remove_file", "remove_dir",
                        "move_file", "copy_file", "shell_exec",
                        "send_email", "send_telegram",
                        "memory_delete",
                    }
                    ADMIN_NETWORK_TOOLS = {"http_request"}
                    
                    if tool_name in ADMIN_ONLY_TOOLS:
                        raise PermissionError(f"Access denied: Tool '{tool_name}' requires ADMIN privileges.")
                    elif tool_name in ADMIN_NETWORK_TOOLS:
                        raise PermissionError(
                            f"Access denied: Tool '{tool_name}' requires ADMIN privileges (network access)."
                        )
                    else:
                        raise PermissionError(
                            f"Access denied: Tool '{tool_name}' is not permitted for caller role '{caller_role}'."
                        )

                await self.hooks.before_execute(execution_context)

                # ── TOOL DISPATCH ──
                func = tool.func
                sig = inspect.signature(func)
                
                if "tool_input" in sig.parameters:
                    result_content = await func(tool_input)
                else:
                    # Fallback to destructuring dictionary parameters
                    result_content = await func(**tool_input)

                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_content,
                    "is_error": False
                }
                await self.hooks.after_execute(execution_context, result)
                return result

            except Exception as e:
                logger.error("Error executing tool %s: %s", tool_name, type(e).__name__)
                from thinkdome.core.error_codes import SandboxErrorCodes
                if isinstance(e, ExecutionHookTimeout):
                    code = "POLICY::HOOK_TIMEOUT"
                    message = str(e)
                elif isinstance(e, PermissionError):
                    code = "AUTH::ACCESS_DENIED"
                    # The policy denial is safe to expose and tells clients
                    # which capability/role contract they violated. Do not
                    # expose arbitrary exception text for other failures.
                    message = str(e) or "Access denied by the sandbox security policy."
                elif isinstance(e, FileNotFoundError):
                    code = SandboxErrorCodes.FILE_NOT_FOUND
                    message = "The requested FileBox path does not exist."
                elif isinstance(e, ValueError):
                    code = SandboxErrorCodes.FILE_INVALID_PATH
                    message = "The tool input was invalid."
                else:
                    code = SandboxErrorCodes.UNKNOWN_ERROR
                    message = "The tool could not complete safely."
                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps({"error": {"code": code, "message": message, "tool": tool_name}}),
                    "is_error": True
                }
                await self.hooks.after_execute(execution_context, result)
                return result
        finally:
            current_tool_context.reset(ctx_token)
            current_username.reset(token)
