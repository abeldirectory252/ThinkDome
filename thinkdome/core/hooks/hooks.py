"""ThinkDome Hook System.

Coordinates extension points for models, executors, and requests.
Supports priority sequencing, synchronous/asynchronous execution, and event execution cancellation.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


class HookCancellation(Exception):
    """Exception raised by a hook callback to cancel the execution chain."""
    pass


class HookManager:
    """Manages registration and execution of priority-based hooks."""

    def __init__(self) -> None:
        # hook_name -> list of (callback, priority)
        self._hooks: Dict[str, List[Tuple[Callable, int]]] = {}

    def register(self, hook_name: str, callback: Callable, priority: int = 100) -> None:
        """Register a callback to a hook name with a priority (lower runs first)."""
        self._hooks.setdefault(hook_name, []).append((callback, priority))
        # Sort hooks immediately
        self._hooks[hook_name].sort(key=lambda item: item[1])
        logger.debug(f"Registered hook '{hook_name}' with priority {priority}")

    async def run(self, hook_name: str, *args, **kwargs) -> None:
        """Execute all callbacks for a hook sequentially in priority order."""
        callbacks = self._hooks.get(hook_name, [])
        for callback, _ in callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except HookCancellation as e:
                logger.warning(f"Hook '{hook_name}' execution cancelled by callback: {callback.__name__}")
                raise e
            except Exception as e:
                logger.error(f"Error running hook '{hook_name}' callback {callback}: {e}")
                raise e

# Global default instance
manager = HookManager()


def register_hook(hook_name: str, priority: int = 100) -> Callable:
    """Decorator to register a function to a hook."""
    def decorator(func: Callable) -> Callable:
        manager.register(hook_name, func, priority)
        return func
    return decorator
