"""Optional Redis cache for short-lived node heartbeat reads."""

from __future__ import annotations

import json
from typing import Any

from thinkdome.control_plane.contracts import NodeHeartbeat


class RedisNodeHeartbeatCache:
    def __init__(self, client: Any, *, prefix: str = "thinkdome:nodes", ttl_seconds: int = 30):
        self.client = client
        self.prefix = prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds

    def _key(self, node_id: str) -> str:
        return f"{self.prefix}:{node_id}"

    def put(self, heartbeat: NodeHeartbeat) -> None:
        self.client.setex(
            self._key(heartbeat.node_id),
            self.ttl_seconds,
            heartbeat.model_dump_json(),
        )

    def get_ready(self) -> list[NodeHeartbeat]:
        result = []
        for key in self.client.scan_iter(match=f"{self.prefix}:*"):
            raw = self.client.get(key)
            if raw:
                payload = raw.decode() if isinstance(raw, bytes) else raw
                heartbeat = NodeHeartbeat.model_validate(json.loads(payload))
                if heartbeat.state.value == "ready":
                    result.append(heartbeat)
        return result
