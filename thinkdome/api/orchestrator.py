"""Orchestrator endpoint for executing tool use blocks."""

from __future__ import annotations

import json
import time
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from thinkdome.api.dependencies import (
    get_orchestrator_service,
    get_current_user,
    get_request_log_service
)
from thinkdome.services.orchestrator_service import OrchestratorService
from thinkdome.services.request_log_service import RequestLogService

router = APIRouter(tags=["orchestrator"])

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
    
    raw_body = await request.body()
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
    username = current_user.get("username", "anonymous")
    key_id = current_user.get("key_id")
    db = request.app.state.db_service
    all_active = db.fetch_all("SELECT * FROM sandboxes WHERE status = 'active'")
    
    eligible_sandboxes = []
    for sb in all_active:
        owner = sb.get("owner")
        # Match if owned by this user, this key, admin, or is a global/anonymous sandbox
        if owner in (username, key_id, "admin", "administrator", "anonymous"):
            eligible_sandboxes.append(sb)

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
            log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms)
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
        result = await orchestrator.execute_tool(data, caller_role=caller_role, sandbox_limits=sandbox_limits)
        
        # Log request and response details
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_svc.log_request(client_ip, current_user, data, result, duration_ms)
        
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
        log_svc.log_request(client_ip, current_user, data, mock_result, duration_ms)
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_res)


