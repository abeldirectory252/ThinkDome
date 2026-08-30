"""Orchestrator endpoint for executing tool use blocks."""
# allowed_scopes = ROLE_SCOPES.get


from __future__ import annotations

import json
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import (
    get_orchestrator_service,
    get_current_user,
    get_current_admin,
    get_request_log_service
)
from thinkdome.platform.orchestration.orchestrator_service import OrchestratorService
from thinkdome.platform.orchestration.request_log import RequestLogService
from thinkdome.core.ui.service import UIManager
from thinkdome.security.identity.core import is_admin_role

router = APIRouter(tags=["orchestrator"])
_MAX_ORCHESTRATOR_BODY_BYTES = 1 * 1024 * 1024

@router.post("/orchestrate")
async def orchestrate_tool(
    request: Request,
    orchestrator: OrchestratorService = Depends(get_orchestrator_service),
    log_svc: RequestLogService = Depends(get_request_log_service),
    current_user: dict = Depends(get_current_user)
):
    """Receive a tool_use block, validate it against schema, execute the tool, and return a tool_result."""
    start_time = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"
    
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_ORCHESTRATOR_BODY_BYTES:
                return JSONResponse(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                     content={"error": {"type": "invalid_request_error",
                                                        "message": "Request body too large."}})
        except ValueError:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST,
                                 content={"error": {"type": "invalid_request_error",
                                                    "message": "Invalid Content-Length."}})
    raw_body = await request.body()
    if len(raw_body) > _MAX_ORCHESTRATOR_BODY_BYTES:
        return JSONResponse(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                             content={"error": {"type": "invalid_request_error",
                                                "message": "Request body too large."}})
    try:
        body_str = raw_body.decode("utf-8")
        if not body_str.strip():
            error_res = {
                "error": {
                    "type": "invalid_request_error",
                    "message": "Empty request body. Please provide a valid JSON payload."
                }
            }
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)
        data = json.loads(body_str)
    except json.JSONDecodeError as e:
        error_res = {
            "error": {
                "type": "invalid_request_error",
                "message": f"Malformed JSON: {str(e)}"
            }
        }
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)
    except Exception as e:
        error_res = {
            "error": {
                "type": "invalid_request_error",
                "message": f"Failed to parse request: {str(e)}"
            }
        }
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)

    # Validate against Orchestrator JSON Schema
    try:
        orchestrator.validate_request(data)
    except ValueError as e:
        error_res = {
            "error": {
                "type": "invalid_request_error",
                "message": f"Validation failed: {str(e)}"
            }
        }
        # Log validation failure
        mock_result = {"is_error": True, "content": f"Validation failed: {str(e)}"}
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms)
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)

    # Ensure there is an active sandbox environment provisioned
    username = current_user.get("username") or current_user.get("workspace_id") or "anonymous"
    key_id = current_user.get("key_id")
    db = request.app.state.db_service
    from thinkdome.security.identity.core import UserIdentity, is_sandbox_accessible

    identity = UserIdentity.from_dict(current_user)

    # Fetch active sandboxes pythonically via ThinkDome ORM
    from thinkdome.apps.sandbox.models import Sandbox
    active_sandboxes = Sandbox.query().filter(status="active").all()
    if not active_sandboxes:
        active_sandboxes = Sandbox.query().filter(status="Running").all()

    all_active = [sb.to_dict() for sb in active_sandboxes]
    if not all_active and hasattr(db, "list_sandboxes"):
        all_active = db.list_sandboxes()

    eligible_sandboxes = [
        sb for sb in all_active if is_sandbox_accessible(sb, identity)
    ]

    if not eligible_sandboxes:
        error_res = {
            "error": {
                "type": "invalid_request_error",
                "message": "No active sandbox environment found. Please create/rent a sandbox first."
            }
        }
        mock_result = {"is_error": True, "content": "No active sandbox environment found. Please create/rent a sandbox first."}
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms)
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)

    # Resolve sandbox choice based on X-Sandbox-Id header
    sandbox_id = request.headers.get("x-sandbox-id") or request.headers.get("X-Sandbox-Id")
    selected_sandbox = None

    if sandbox_id:
        # Search among eligible active sandboxes
        for sb in eligible_sandboxes:
            if sb.get("sandbox_id") == sandbox_id:
                selected_sandbox = sb
                break
        if not selected_sandbox:
            error_res = {
                "error": {
                    "type": "invalid_request_error",
                    "message": f"Requested sandbox '{sandbox_id}' is not active, not found, or not owned by you."
                }
            }
            mock_result = {"is_error": True, "content": f"Requested sandbox '{sandbox_id}' not found or inactive."}
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms, sandbox_id=sandbox_id)
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)
    else:
        # Fallback to the most recently created active sandbox
        selected_sandbox = eligible_sandboxes[-1]

    sandbox_limits = {
        "memory_mb": selected_sandbox.get("memory_mb"),
        "cpu_cores": selected_sandbox.get("cpu_cores"),
        "timeout_sec": selected_sandbox.get("timeout_sec"),
        "network_enabled": selected_sandbox.get("network_enabled"),
    }

    # Process and execute
    if data.get("type") == "tool_use":
        caller_role = current_user.get("role", "LLM")
        
        # Execute directly via OrchestratorService — handles all tools including
        # run_code (via ExecutionService) and file ops. The distributed scheduler
        # queue is only needed when separate worker containers consume tasks.
        result = await orchestrator.execute_tool(
            tool_use=data,
            caller_role=caller_role,
            sandbox_limits=sandbox_limits,
            username=username,
            sandbox_id=selected_sandbox.get("sandbox_id"),
        )
        
        # Log request and response details
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_svc.log_request(client_ip, current_user, data, result, duration_ms, sandbox_id=selected_sandbox.get("sandbox_id"))
        
        return result
    else:
        # Just in case schema allowed it but it's not a tool_use
        error_res = {
            "error": {
                "type": "invalid_request_error",
                "message": "Only 'tool_use' blocks are accepted for execution."
            }
        }
        mock_result = {"is_error": True, "content": "Only 'tool_use' blocks are accepted for execution."}
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms, sandbox_id=selected_sandbox.get("sandbox_id"))
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)


@router.get("/tools")
async def list_tools(current_user: dict = Depends(get_current_user)):
    """Retrieve all registered tools and their metadata."""
    import os
    from thinkdome.platform.orchestration.tools import registry
    from thinkdome.platform.orchestration.orchestrator_service import ROLE_SCOPES
    roles = {str(value).upper() for value in (current_user.get("roles") or [current_user.get("role", "LLM")])}
    role = str(current_user.get("role", "LLM")).upper()
    allowed_scopes = set().union(*(ROLE_SCOPES.get(value, ROLE_SCOPES["LLM"]) for value in roles))
    metadata = UIManager().get_mcp_tool_metadata()
    tools = registry.list_all_tools()
    admin = any(is_admin_role(value) for value in roles)
    tools = [t for t in tools if admin or metadata.get(t.name, {}).get("is_active", True)]
    tools = [t for t in tools if admin or not metadata.get(t.name, {}).get("allowed_roles") or roles.intersection({str(item).upper() for item in metadata.get(t.name, {}).get("allowed_roles", [])})]
    tools = [t for t in tools if not t.required_scope or t.required_scope in allowed_scopes]
    
    response = []
    for t in tools:
        schema = None
        if t.input_schema is not None:
            if hasattr(t.input_schema, "model_json_schema"):
                schema = t.input_schema.model_json_schema()
            else:
                schema = t.input_schema

        response.append({
            "name": t.name,
            "title": metadata.get(t.name, {}).get("title") or t.name,
            "description": metadata.get(t.name, {}).get("description") or t.description,
            "required_scope": t.required_scope,
            "app_name": t.app_name,
            "is_active": metadata.get(t.name, {}).get("is_active", True),
            "allowed_roles": metadata.get(t.name, {}).get("allowed_roles", []),
            "is_runtime_registered": True,
            "input_schema": schema
        })
    runtime_names = {item["name"] for item in response}
    for name, item in metadata.items():
        if name in runtime_names:
            continue
        if not admin and (not item.get("is_active", True) or (item.get("allowed_roles") and not roles.intersection({str(value).upper() for value in item.get("allowed_roles", [])}))):
            continue
        response.append({
            "name": name,
            "title": item.get("title") or name,
            "description": item.get("description", ""),
            "required_scope": item.get("required_scope"),
            "app_name": item.get("app_name", "managed"),
            "is_active": item.get("is_active", True),
            "allowed_roles": item.get("allowed_roles", []),
            "is_runtime_registered": False,
            "input_schema": item.get("input_schema"),
        })
    return response


class McpToolMetadataPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=2000)
    is_active: bool = True
    allowed_roles: List[str] = Field(default_factory=list, max_length=100)
    required_scope: Optional[str] = Field(default=None, max_length=255)


@router.post("/tools/metadata", status_code=201)
async def create_mcp_tool_metadata(payload: McpToolMetadataPayload, current_user: dict = Depends(get_current_admin)):
    """Create or register the policy metadata for an MCP tool."""
    return UIManager().register_mcp_tool(payload.model_dump())


@router.put("/tools/metadata/{tool_name}")
async def update_mcp_tool_metadata(tool_name: str, payload: McpToolMetadataPayload, current_user: dict = Depends(get_current_admin)):
    if payload.name != tool_name:
        raise HTTPException(status_code=400, detail="Tool name cannot be changed")
    return UIManager().register_mcp_tool(payload.model_dump())


@router.delete("/tools/metadata/{tool_name}")
async def delete_mcp_tool_metadata(tool_name: str, current_user: dict = Depends(get_current_admin)):
    return {"deleted": UIManager().delete_mcp_tool(tool_name)}
