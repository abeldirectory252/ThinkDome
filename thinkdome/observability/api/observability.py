"""Observability, Prometheus metrics, and Postgres audit trail endpoints."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from thinkdome.observability.metrics.prometheus import ACTIVE_SANDBOXES, POOL_HIT_RATE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics(request: Request):
    """Scrape Prometheus metrics."""
    # Update active gauges dynamically before returning metrics
    db = request.app.state.db_service
    pool = request.app.state.pool_manager
    
    try:
        # Update active sandbox counts per backend
        docker_active = await db.fetch_val(
            "SELECT COUNT(*) FROM sandboxes WHERE status = 'active' AND backend_type = 'docker'"
        )
        k8s_active = await db.fetch_val(
            "SELECT COUNT(*) FROM sandboxes WHERE status = 'active' AND backend_type = 'kubernetes'"
        )
        ACTIVE_SANDBOXES.labels(backend_type="docker").set(docker_active or 0)
        ACTIVE_SANDBOXES.labels(backend_type="kubernetes").set(k8s_active or 0)
        
        # Update pool metrics
        pool_status = pool.get_status()
        POOL_HIT_RATE.set(pool_status.get("hit_rate", 0.0))
        
    except Exception as e:
        logger.error(f"Failed to query database metric updates: {e}")

    # Generate and return latest metrics format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/logs/executions")
async def execution_logs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    sandbox_id: str = None,
    tool_name: str = None,
):
    """Query execution request logs from PostgreSQL."""
    db = request.app.state.db_service
    try:
        logs = await db.get_request_logs(
            limit=limit,
            offset=offset,
            sandbox_id=sandbox_id,
            tool_name=tool_name
        )
        total = await db.fetch_val("SELECT COUNT(*) FROM request_logs")
        return {"logs": logs, "total": total or 0}
    except Exception as e:
        logger.error(f"Failed to query execution logs: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Failed to retrieve logs: {str(e)}"}
        )


@router.get("/audit/files")
async def file_audit(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    actor: str = None,
    action: str = None,
):
    """File operation audit trail from PostgreSQL."""
    db = request.app.state.db_service
    try:
        events = await db.get_audit_logs(
            limit=limit,
            offset=offset,
            actor=actor,
            action=action
        )
        total = await db.fetch_val("SELECT COUNT(*) FROM audit_logs")
        return {"events": events, "total": total or 0}
    except Exception as e:
        logger.error(f"Failed to query audit trail: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Failed to retrieve audit trail: {str(e)}"}
        )


@router.post("/debug/executor")
async def debug_executor(request: Request):
    """Dump executor state (admin only)."""
    exec_svc = request.app.state.execution_service
    health = await exec_svc.health_check()
    return {
        "executor_health": health,
        "active_executors": list(exec_svc._executors.keys()),
    }
