"""ThinkDome Event Bus.

Handles asynchronous publish/subscribe message routing for local events,
distributed Redis integration, and WebSocket client broadcasts.
"""

from __future__ import annotations

import inspect
import logging
import json
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventBus:
    """Core message bus processing event dispatch and subscription matching."""

    def __init__(self) -> None:
        # event_name -> list of subscriber callbacks
        self._listeners: Dict[str, List[Callable]] = {}
        self._websocket_relay: Optional[Callable[[str, Any], None]] = None
        self._redis_client = None

    def on(self, event_name: str, callback: Callable) -> None:
        """Subscribe a listener callback to an event type."""
        self._listeners.setdefault(event_name, []).append(callback)
        logger.debug(f"Subscribed callback to event: {event_name}")

    async def emit(self, event_name: str, data: Any) -> None:
        """Publish event and notify all registered local and distributed subscribers."""
        logger.info(f"⚡ Event emitted: {event_name}")

        # 1. Notify local subscribers
        callbacks = self._listeners.get(event_name, [])
        for callback in callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Error executing event listener {callback} on {event_name}: {e}")

        # 2. Notify WebSocket clients (e.g., frontend updates)
        if self._websocket_relay:
            try:
                await self._websocket_relay(event_name, data)
            except Exception as e:
                logger.error(f"WebSocket relay failed for event {event_name}: {e}")

        # 3. Distribute to Redis pub/sub if enabled
        if self._redis_client:
            try:
                payload = json.dumps({"event": event_name, "data": data})
                await self._redis_client.publish("thinkdome_events", payload)
            except Exception as e:
                logger.error(f"Redis event publication failed for {event_name}: {e}")

    def register_websocket_relay(self, relay_fn: Callable[[str, Any], None]) -> None:
        """Bind gateway WebSocket manager to broadcast events to client interfaces."""
        self._websocket_relay = relay_fn

    def set_redis_client(self, client: Any) -> None:
        """Bind active Redis connection to distribute events across container workers."""
        self._redis_client = client


# Global default instance
bus = EventBus()


def on(event_name: str) -> Callable:
    """Decorator to subscribe a function to an event."""
    def decorator(func: Callable) -> Callable:
        bus.on(event_name, func)
        return func
    return decorator


async def emit(event_name: str, data: Any) -> None:
    """Helper function to emit an event using the default EventBus instance."""
    await bus.emit(event_name, data)
