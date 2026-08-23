"""Execution endpoints."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from thinkdome.core.dependencies import get_execution_service, get_current_user
from thinkdome.sandbox.core.models import (
    ExecuteRequest,
    ExecuteResponse,
    BatchExecuteRequest,
    BatchExecuteResponse,
)
from thinkdome.sandbox.core.service import ExecutionService

router = APIRouter(tags=["execution"])
logger = logging.getLogger(__name__)


@router.post("/execute", response_model=ExecuteResponse)
async def execute_code(
    request: ExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
    user: dict = Depends(get_current_user),
):
    """Execute a code snippet in an isolated environment."""
    try:
        # Never trust client-supplied identity/role fields for workspace or
        # resource policy decisions; derive them from the authenticated token.
        identity_request = request.model_copy(update={
            "username": str(user.get("workspace_id", user.get("username", ""))).lower(),
            "caller_role": str(user.get("role", "AGENT_STANDARD")),
        })
        return await svc.execute(identity_request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Execution request failed")
        raise HTTPException(status_code=500, detail="Execution failed. Please try again later.")


@router.post("/execute/batch", response_model=BatchExecuteResponse)
async def execute_batch(
    request: BatchExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
    user: dict = Depends(get_current_user),
):
    """Execute multiple code blocks sequentially."""
    try:
        identity_requests = [item.model_copy(update={
            "username": str(user.get("workspace_id", user.get("username", ""))).lower(),
            "caller_role": str(user.get("role", "AGENT_STANDARD")),
        }) for item in request.executions]
        return await svc.execute_batch(request.model_copy(update={"executions": identity_requests}))
    except Exception:
        logger.exception("Batch execution request failed")
        raise HTTPException(status_code=500, detail="Batch execution failed. Please try again later.")


@router.post("/execute/stream")
async def execute_stream(
    request: ExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
    user: dict = Depends(get_current_user),
):
    """Stream execution output via Server-Sent Events."""
    identity_request = request.model_copy(update={
        "username": str(user.get("workspace_id", user.get("username", ""))).lower(),
        "caller_role": str(user.get("role", "AGENT_STANDARD")),
    })
    return EventSourceResponse(svc.execute_stream(identity_request))
