"""Execution-node lease registry backed by the ThinkDome ORM."""

from __future__ import annotations

import time
import asyncio
from typing import Optional

from thinkdome.apps.sandbox.models import ExecutionNode
from thinkdome.control_plane.contracts import NodeHeartbeat, NodeState
from thinkdome.control_plane.repository import ControlPlaneRepository


class NodeRegistry:
    """Maintains node leases and exposes only currently healthy nodes."""

    def __init__(self, repository: ControlPlaneRepository, cache=None) -> None:
        self.repository = repository
        self.cache = cache

    def heartbeat(self, heartbeat: NodeHeartbeat) -> ExecutionNode:
        result = self.repository.record_heartbeat(heartbeat)
        if self.cache:
            try:
                self.cache.put(heartbeat)
            except Exception:
                pass
        return result

    def ready_nodes(self) -> list[NodeHeartbeat]:
        if self.cache:
            try:
                cached = self.cache.get_ready()
                if cached:
                    return cached
            except Exception:
                pass
        return self.repository.get_ready_heartbeats()

    def reconcile_expired(self, now: Optional[float] = None) -> int:
        """Mark expired ready/draining nodes offline through the ORM."""
        current = time.time() if now is None else now
        changed = 0
        for node in ExecutionNode.query().all():
            if node.state in (NodeState.READY.value, NodeState.DRAINING.value) and node.lease_expires_at <= current:
                node.state = NodeState.OFFLINE.value
                node.save()
                changed += 1
        return changed


class NodeLeaseReconciler:
    """Periodic lease reconciliation for a control-plane process."""

    def __init__(self, registry: NodeRegistry, interval_seconds: float = 5.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.registry = registry
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="node-lease-reconciler")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.registry.reconcile_expired()
                reclaim = getattr(self.registry.repository, "reconcile_expired_placements", None)
                if reclaim:
                    reclaim()
            except Exception:
                # A failed reconciliation must not kill the control-plane loop.
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue
