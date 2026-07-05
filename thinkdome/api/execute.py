"""Execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from thinkdome.api.dependencies import get_execution_service
from thinkdome.models.execution import (
    ExecuteRequest,
    ExecuteResponse,
    BatchExecuteRequest,
    BatchExecuteResponse,
)
from thinkdome.services.execution_service import ExecutionService

router = APIRouter(tags=["execution"])


@router.post("/execute", response_model=ExecuteResponse)
async def execute_code(
    request: ExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
):
    """Execute a code snippet in an isolated environment."""
    try:
        return await svc.execute(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")


@router.post("/execute/batch", response_model=BatchExecuteResponse)
async def execute_batch(
    request: BatchExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
):
    """Execute multiple code blocks sequentially."""
    try:
        return await svc.execute_batch(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute/stream")
async def execute_stream(
    request: ExecuteRequest,
    svc: ExecutionService = Depends(get_execution_service),
):
    """Stream execution output via Server-Sent Events."""
    return EventSourceResponse(svc.execute_stream(request))
