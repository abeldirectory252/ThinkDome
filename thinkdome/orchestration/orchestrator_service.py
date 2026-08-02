import contextvars
import os
import json
import logging
import inspect
from pathlib import Path
from typing import Any, Optional

from thinkdome.core.config import Settings
from thinkdome.execution.core.service import ExecutionService
from thinkdome.orchestration.search.service import SearchService
from thinkdome.execution.core.models import ExecuteRequest
from thinkdome.orchestration.search.models import SearchRequest

# Dynamic tools registration and schema imports
from thinkdome.orchestration.tools import registry, ToolContext, current_tool_context

logger = logging.getLogger(__name__)

# Context variable to hold username for current execution thread/task
current_username: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_username", default=None)

# ── Role-Based Access Control (RBAC) Scopes Matrix ──
ROLE_SCOPES = {
    "LLM": {"code:run", "memory:read", "memory:write"},
    "WEB": {
        "code:run", "file:read", "file:write",
        "memory:read", "memory:write"
    },
    "SDK": {
        "code:run", "file:read", "file:write",
        "web:search", "memory:read", "memory:write"
    },
    "CURL": {
        "code:run", "file:read", "file:write",
        "web:search", "memory:read", "memory:write"
    },
    "ORCH": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "admin:all"
    },
    "IDE": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "pty:all"
    },
    "ADMIN": {
        "code:run", "file:read", "file:write", "file:destructive",
        "web:search", "memory:read", "memory:write", "memory:delete",
        "network:all", "shell:run", "comms:send", "pty:all", "admin:all"
    }
}


class OrchestratorService:
    """Validates and executes tool use blocks like an LLM orchestrator."""

    def __init__(
        self,
        settings: Settings,
        execution_service: ExecutionService,
        search_service: SearchService,
        security_scanner = None,
        credential_vault = None,
    ) -> None:
        self.settings = settings
        self.execution_service = execution_service
        self.search_service = search_service
        self.security_scanner = security_scanner
        self.credential_vault = credential_vault
        
        # Set workspace root to the project root directory
        self.workspace_root = Path(__file__).resolve().parents[3]
        logger.info(f"OrchestratorService initialized with workspace root: {self.workspace_root}")

    def validate_request(self, data: dict) -> None:
        """Validate request against Pydantic Python schema."""
        from thinkdome.orchestration.orchestrator_models import ToolUseRequest
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
        if not username:
            username = "anonymous"
        user_dir = Path(self.settings.FILE_STORAGE_DIR) / "workspaces" / username
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

            logger.info(f"Executing tool {tool_name} (id: {tool_id}) with inputs {tool_input} (caller: {caller_role})")
            
            try:
                # Retrieve the tool from our dynamic registry
                tool = registry.get_tool(tool_name)
                if not tool:
                    raise ValueError(f"Unknown tool name: {tool_name}")

                # Ensure non-core (app) tools are active in the current site config
                if tool.app_name != "core":
                    site_name = os.environ.get("THINKDOME_SITE", "personal")
                    active_tools = registry.get_active_tools(site_name)
                    active_names = {t.name for t in active_tools}
                    if tool_name not in active_names:
                        raise PermissionError(
                            f"Access denied: Tool '{tool_name}' is inactive/disabled for the current site context."
                        )

                # ── PRIVILEGE VERIFICATION ──
                role_upper = (caller_role or "LLM").upper()
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

                # ── TOOL DISPATCH ──
                func = tool.func
                sig = inspect.signature(func)
                
                if "tool_input" in sig.parameters:
                    result_content = await func(tool_input)
                else:
                    # Fallback to destructuring dictionary parameters
                    result_content = await func(**tool_input)

                return {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_content,
                    "is_error": False
                }

            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error executing tool '{tool_name}': {str(e)}",
                    "is_error": True
                }
        finally:
            current_tool_context.reset(ctx_token)
            current_username.reset(token)
