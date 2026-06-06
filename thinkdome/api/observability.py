"""Observability, metrics, and audit endpoints."""

from __future__ import annotations

import time
from fastapi import APIRouter, Request

router = APIRouter(tags=["observability"])

_start_time = time.time()


@router.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics (simplified)."""
    uptime = time.time() - _start_time
    return {
        "uptime_seconds": round(uptime, 2),
        "info": "Full Prometheus metrics coming soon â€” integrate prometheus_client for production",
    }


@router.get("/logs/executions")
async def execution_logs():
    """Query execution logs (placeholder)."""
    return {"logs": [], "total": 0, "note": "Execution log storage not yet implemented"}


@router.get("/audit/files")
async def file_audit():
    """File operation audit trail (placeholder)."""
    return {"events": [], "total": 0, "note": "Audit trail not yet implemented"}


@router.post("/debug/executor")
async def debug_executor(request: Request):
    """Dump executor state (admin only)."""
    exec_svc = request.app.state.execution_service
    health = await exec_svc.health_check()
    return {
        "executor_health": health,
        "active_executors": list(exec_svc._executors.keys()),
    }
