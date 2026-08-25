"""Execution hook framework for sandbox/orchestrator boundaries."""

from __future__ import annotations

import inspect
import logging
import asyncio
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Optional

logger = logging.getLogger(__name__)


def freeze_execution_value(value: Any) -> Any:
    """Recursively freeze plugin-visible execution data."""
    if isinstance(value, dict):
        return MappingProxyType({str(k): freeze_execution_value(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_execution_value(v) for v in value)
    if isinstance(value, set):
        return frozenset(freeze_execution_value(v) for v in value)
    return value


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable description of an execution about to cross the sandbox boundary."""

    tool_use: Mapping[str, Any]
    sandbox_id: Optional[str]
    username: str
    caller_role: str


class ExecutionHookError(RuntimeError):
    """Base error raised by the execution hook pipeline."""


class ExecutionHookRejected(ExecutionHookError, PermissionError):
    """A before-execution hook deliberately denied the operation."""


class ExecutionHookTimeout(ExecutionHookRejected, TimeoutError):
    """A hook exceeded the configured execution-policy deadline."""


@dataclass(frozen=True)
class HookRegistration:
    token: int
    priority: int
    hook: ExecutionHook


class ExecutionHook(Protocol):
    """Hook contract. Before failures deny execution; after failures are isolated."""

    async def before_execute(self, context: ExecutionContext) -> None: ...

    async def after_execute(self, context: ExecutionContext, result: Mapping[str, Any]) -> None: ...


class ExecutionHookManager:
    """Deterministic, priority-ordered hook pipeline."""

    def __init__(self, audit_hook: Optional[ExecutionHook] = None, *, timeout_seconds: float = 5.0) -> None:
        self._audit_hook = audit_hook
        self._timeout_seconds = timeout_seconds
        self._hooks: list[HookRegistration] = []
        self._sequence = 0

    def set_audit_hook(self, hook: Optional[ExecutionHook]) -> None:
        self._audit_hook = hook

    def register(self, hook: ExecutionHook, *, priority: int = 100) -> HookRegistration:
        registration = HookRegistration(self._sequence, priority, hook)
        self._hooks.append(registration)
        self._sequence += 1
        self._hooks.sort(key=lambda item: (item.priority, item.token))
        return registration

    def unregister(self, registration: HookRegistration) -> bool:
        before = len(self._hooks)
        self._hooks = [item for item in self._hooks if item.token != registration.token]
        return len(self._hooks) != before

    async def before_execute(self, context: ExecutionContext) -> None:
        hooks = ([self._audit_hook] if self._audit_hook is not None else [])
        hooks.extend(item.hook for item in self._hooks)
        for hook in hooks:
            try:
                result = hook.before_execute(context)
                if inspect.isawaitable(result):
                    try:
                        await asyncio.wait_for(result, timeout=self._timeout_seconds)
                    except asyncio.TimeoutError as exc:
                        raise ExecutionHookTimeout(
                            f"Execution policy hook exceeded the {self._timeout_seconds:g}-second deadline"
                        ) from exc
            except ExecutionHookError:
                raise
            except Exception as exc:
                raise ExecutionHookRejected("Execution denied by hook policy") from exc

    async def after_execute(self, context: ExecutionContext, result: Mapping[str, Any]) -> None:
        hooks = ([self._audit_hook] if self._audit_hook is not None else [])
        hooks.extend(item.hook for item in self._hooks)
        for hook in hooks:
            try:
                callback = hook.after_execute(context, result)
                if inspect.isawaitable(callback):
                    await asyncio.wait_for(callback, timeout=self._timeout_seconds)
            except Exception as exc:
                logger.error("Execution after-hook failed: %s", type(exc).__name__)
