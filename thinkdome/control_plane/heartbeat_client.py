"""Node-agent client for renewing control-plane node leases."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

import httpx

from thinkdome.control_plane.contracts import NodeHeartbeat


class HeartbeatPublishError(RuntimeError):
    """The control plane rejected or could not receive a heartbeat."""


class NodeHeartbeatClient:
    """Publishes node heartbeats over the private control-plane transport."""

    def __init__(
        self,
        control_plane_url: str,
        node_id: str,
        heartbeat_factory: Callable[[], NodeHeartbeat],
        *,
        client: Optional[httpx.AsyncClient] = None,
        interval_seconds: float = 10.0,
    ) -> None:
        if not control_plane_url:
            raise ValueError("control_plane_url is required")
        if not node_id:
            raise ValueError("node_id is required")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.control_plane_url = control_plane_url.rstrip("/")
        self.node_id = node_id
        self.heartbeat_factory = heartbeat_factory
        self.client = client
        self.interval_seconds = interval_seconds
        self._stop = asyncio.Event()

    async def publish_once(self) -> dict:
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=10.0)
        try:
            heartbeat = self.heartbeat_factory()
            if heartbeat.node_id != self.node_id:
                raise HeartbeatPublishError("heartbeat node ID does not match configured node ID")
            response = await client.post(
                f"{self.control_plane_url}/internal/control-plane/nodes/heartbeat",
                json=heartbeat.model_dump(mode="json"),
                headers={"X-ThinkDome-Node-ID": self.node_id},
            )
            if response.status_code >= 400:
                raise HeartbeatPublishError(
                    f"control plane rejected heartbeat ({response.status_code})"
                )
            return response.json()
        except httpx.HTTPError as exc:
            raise HeartbeatPublishError(f"heartbeat transport failed: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

    async def run(self) -> None:
        """Publish until ``stop`` is called; transient failures are retried."""
        while not self._stop.is_set():
            try:
                await self.publish_once()
            except HeartbeatPublishError:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
