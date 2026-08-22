"""Dedicated node-agent application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from thinkdome.control_plane.auth import NodeAuthorizationSigner
from thinkdome.control_plane.microvm_adapter import MicroVMNodeAdapter
from thinkdome.control_plane.node_agent import NodeAgent
from thinkdome.control_plane.node_api import create_node_router
from thinkdome.control_plane.heartbeat_client import NodeHeartbeatClient
from thinkdome.control_plane.capacity import discover_capacity
from thinkdome.control_plane.contracts import NodeHeartbeat, NodeState
from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.microvm.executor import MicroVMExecutor


def _node_key(settings: Settings) -> bytes:
    value = settings.NODE_AUTH_KEY_HEX
    if not value:
        raise RuntimeError("NODE_AUTH_KEY_HEX must be configured for the node agent")
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise RuntimeError("NODE_AUTH_KEY_HEX must be valid hexadecimal") from exc
    if len(key) < 32:
        raise RuntimeError("NODE_AUTH_KEY_HEX must contain at least 32 bytes")
    return key


def create_node_app(settings: Optional[Settings] = None) -> FastAPI:
    """Build a private node-agent app; the public API is not mounted."""
    settings = settings or Settings()
    settings.validate_production_runtime()
    executor = MicroVMExecutor(settings)
    adapter = MicroVMNodeAdapter(executor)
    signer = NodeAuthorizationSigner(_node_key(settings), key_id=settings.NODE_ID or "current")
    heartbeat_client = None
    if settings.CONTROL_PLANE_INTERNAL_URL:
        def heartbeat() -> NodeHeartbeat:
            return NodeHeartbeat(
                node_id=settings.NODE_ID,
                region=settings.NODE_REGION,
                state=NodeState.READY,
                capacity=discover_capacity(active_sandboxes=len(executor.instances)),
                orchestrator_version="thinkdome-node-agent",
            )
        heartbeat_client = NodeHeartbeatClient(
            settings.CONTROL_PLANE_INTERNAL_URL,
            settings.NODE_ID,
            heartbeat,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await executor.initialize()
        heartbeat_task = None
        if heartbeat_client:
            heartbeat_task = asyncio.create_task(heartbeat_client.run())
        yield
        if heartbeat_client:
            heartbeat_client.stop()
        if heartbeat_task:
            await heartbeat_task
        await executor.shutdown()

    app = FastAPI(
        title="ThinkDome Node Agent",
        description="Private node-local sandbox orchestrator endpoint",
        lifespan=lifespan,
    )
    app.include_router(create_node_router(NodeAgent(signer, adapter)))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "node_id": settings.NODE_ID, "region": settings.NODE_REGION}

    return app
