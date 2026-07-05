"""Health and readiness endpoints."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request):
    """Readiness probe â€” checks executor health."""
    exec_svc = request.app.state.execution_service
    health = await exec_svc.health_check()
    all_ready = all(health.values()) if health else False
    return {
        "status": "ready" if all_ready else "not_ready",
        "executors": health,
    }
