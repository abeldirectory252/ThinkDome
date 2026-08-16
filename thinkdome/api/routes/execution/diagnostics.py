"""FastAPI routes for Sandbox Diagnostics API (logs, inspect, events, summary).

Provides diagnostic inspection endpoints per sandbox.
Inspired by OpenSandbox DevOps API.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from thinkdome.core.error_codes import SandboxErrorCodes

router = APIRouter(tags=["Diagnostics"])


@router.get(
    "/sandboxes/{sandbox_id}/diagnostics/logs",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Plain text sandbox logs", "content": {"text/plain": {}}},
        404: {"description": "Sandbox not found"},
    },
)
def get_sandbox_logs(
    request: Request,
    sandbox_id: str,
    tail: int = Query(100, ge=1, le=10000, description="Number of trailing log lines"),
    since: Optional[str] = Query(None, description="Logs newer than duration (e.g. 10m, 1h)"),
    container: Optional[str] = Query(None, description="Optional container name"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> PlainTextResponse:
    """Retrieve diagnostic container logs for a sandbox."""
    diagnostics_service = getattr(request.app.state, "diagnostics_service", None)
    if not diagnostics_service:
        return PlainTextResponse(content="Diagnostics service not initialized.", status_code=501)

    logs = diagnostics_service.get_logs(
        sandbox_id, tail=tail, since=since, container_name=container
    )
    return PlainTextResponse(content=logs)


@router.get(
    "/sandboxes/{sandbox_id}/diagnostics/inspect",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Container inspection JSON as plain text", "content": {"text/plain": {}}},
        404: {"description": "Sandbox not found"},
    },
)
def get_sandbox_inspect(
    request: Request,
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> PlainTextResponse:
    """Retrieve detailed inspection info for a sandbox container."""
    diagnostics_service = getattr(request.app.state, "diagnostics_service", None)
    if not diagnostics_service:
        return PlainTextResponse(content="Diagnostics service not initialized.", status_code=501)

    inspect_text = diagnostics_service.get_inspect(sandbox_id)
    return PlainTextResponse(content=inspect_text)


@router.get(
    "/sandboxes/{sandbox_id}/diagnostics/events",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Plain text events or JSON events depending on query"},
    },
)
def get_sandbox_events(
    request: Request,
    sandbox_id: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of events"),
    format: str = Query("text", description="Output format: 'text' or 'json'"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    """Retrieve diagnostic events for a sandbox."""
    diagnostics_service = getattr(request.app.state, "diagnostics_service", None)
    if not diagnostics_service:
        if format == "json":
            raise HTTPException(
                status_code=501,
                detail={"code": SandboxErrorCodes.UNKNOWN_ERROR, "message": "Diagnostics service not initialized."},
            )
        return PlainTextResponse(content="Diagnostics service not initialized.", status_code=501)

    if format == "json":
        events_list = diagnostics_service.get_events_list(sandbox_id, limit=limit)
        return JSONResponse(content={"sandbox_id": sandbox_id, "events": events_list})

    events_text = diagnostics_service.get_events(sandbox_id, limit=limit)
    return PlainTextResponse(content=events_text)


@router.get(
    "/sandboxes/{sandbox_id}/diagnostics/summary",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Combined diagnostics summary (inspect + events + logs)", "content": {"text/plain": {}}},
    },
)
def get_sandbox_diagnostics_summary(
    request: Request,
    sandbox_id: str,
    tail: int = Query(50, ge=1, le=10000, description="Number of trailing log lines"),
    event_limit: int = Query(20, ge=1, le=500, description="Maximum number of events"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> PlainTextResponse:
    """One-shot diagnostics summary combining inspect + events + logs."""
    diagnostics_service = getattr(request.app.state, "diagnostics_service", None)
    if not diagnostics_service:
        return PlainTextResponse(content="Diagnostics service not initialized.", status_code=501)

    summary = diagnostics_service.get_summary(sandbox_id, log_tail=tail, event_limit=event_limit)
    return PlainTextResponse(content=summary)
