"""Private control-plane listener for node orchestration traffic."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from thinkdome.control_plane.registry import NodeLeaseReconciler, NodeRegistry
from thinkdome.control_plane.registry_api import create_registry_router
from thinkdome.control_plane.cache import RedisNodeHeartbeatCache


def create_internal_control_plane_app(
    registry: NodeRegistry,
    *,
    reconcile_interval_seconds: float = 5.0,
    redis_url: str | None = None,
    redis_enabled: bool = True,
    redis_ttl_seconds: int = 30,
) -> FastAPI:
    """Build an app containing no public user or execution routes."""
    if redis_enabled and redis_url and registry.cache is None:
        try:
            import redis
            registry.cache = RedisNodeHeartbeatCache(
                redis.Redis.from_url(redis_url), ttl_seconds=redis_ttl_seconds
            )
        except Exception:
            # ORM remains authoritative when Redis is unavailable or optional
            # dependency installation is omitted.
            registry.cache = None
    reconciler = NodeLeaseReconciler(registry, reconcile_interval_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await reconciler.start()
        yield
        await reconciler.stop()

    app = FastAPI(
        title="ThinkDome Internal Control Plane",
        description="Private node registration and reconciliation listener",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(create_registry_router(registry))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "component": "control-plane-internal"}

    return app
