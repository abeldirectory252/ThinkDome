"""RabbitMQ-backed scheduler facade for ThinkDome.

Delegates task execution to a distributed RabbitMQ queue, making the
scheduler fully stateless across multiple instances.

If no broker is present (e.g. during unit tests), it falls back to
direct execution to ensure backward compatibility and local testing capability.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional
from thinkdome.platform.tasks.rabbitmq import TaskBroker, TaskMessage, TaskResult

logger = logging.getLogger(__name__)


class ScheduledTask:
    """Mock ScheduledTask to preserve compatibility with existing scheduler API."""
    def __init__(self, task_id: str, status: str = "queued", result: Optional[dict] = None):
        self.task_id = task_id
        self.status = status
        self.result = result or {}

    def __getitem__(self, key):
        return self.result[key]

    def get(self, key, default=None):
        return self.result.get(key, default)

    def keys(self):
        return self.result.keys()


class Scheduler:
    """Thin facade around RabbitMQ TaskBroker.

    Interface matches original local scheduler signature to prevent breaking callers.
    """

    def __init__(
        self,
        partition_count: int = 4,
        max_concurrency_per_partition: int = 50,
        rebalance_threshold: float = 0.3,
    ) -> None:
        self.broker: Optional[TaskBroker] = None
        self.executor_fn: Optional[Callable] = None
        self._total_submitted: int = 0
        self._total_completed: int = 0
        self._total_failed: int = 0

    async def start(
        self,
        executor_fn: Optional[Callable] = None,
        broker: Optional[TaskBroker] = None,
    ) -> None:
        """Start the scheduler facade with the given executor and robust broker."""
        self.executor_fn = executor_fn
        import os
        if os.environ.get("EXECUTOR_BACKEND") == "subprocess":
            self.broker = None
            logger.info("📋 Subprocess executor detected: forcing local execution in scheduler (bypassing queue)")
        else:
            self.broker = broker
        logger.info("📋 Distributed scheduler facade initialized")

    async def stop(self) -> None:
        """Stop the scheduler facade."""
        logger.info("📋 Distributed scheduler facade stopped")

    async def submit(
        self,
        task_id: str,
        payload: Any,
        deadline_ms: float = 10000,
        caller_role: str = "LLM",
        username: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        sandbox_limits: Optional[dict] = None,
        trace_id: Optional[str] = None,
    ) -> ScheduledTask:
        """Submit a task for orchestration.

        If a RabbitMQ broker is active, it dispatches over the network and blocks
        until completion (RPC pattern). Otherwise, it falls back to direct execution.
        """
        self._total_submitted += 1

        if self.broker:
            # Wrap standard payload in tool_use dict if it's raw python code / simple string
            tool_use = payload
            if not isinstance(payload, dict):
                tool_use = {
                    "id": task_id,
                    "name": "run_code",
                    "input": {
                        "language": "python",
                        "code": str(payload)
                    }
                }

            task_msg = TaskMessage(
                task_id=task_id,
                tool_use=tool_use,
                caller_role=caller_role,
                username=username,
                sandbox_id=sandbox_id,
                sandbox_limits=sandbox_limits,
                deadline_ms=deadline_ms,
                trace_id=trace_id,
            )

            try:
                result: TaskResult = await self.broker.publish_and_wait(
                    task_msg,
                    timeout=deadline_ms / 1000.0,
                )
                if result.is_error:
                    self._total_failed += 1
                    return ScheduledTask(task_id, "failed", result.result)
                else:
                    self._total_completed += 1
                    return ScheduledTask(task_id, "completed", result.result)
            except Exception as e:
                logger.error(f"Failed to process RPC task {task_id}: {e}")
                self._total_failed += 1
                return ScheduledTask(task_id, "failed", {"is_error": True, "content": str(e)})

        else:
            # Local fallback for unit tests
            task = ScheduledTask(task_id, "queued")
            if self.executor_fn:
                try:
                    task.status = "running"
                    
                    # Convert raw payload to tool_use if needed
                    tool_use = payload
                    if not isinstance(payload, dict):
                        tool_use = {
                            "id": task_id,
                            "name": "run_code",
                            "input": {
                                "language": "python",
                                "code": str(payload)
                            }
                        }
                    
                    try:
                        if asyncio.iscoroutinefunction(self.executor_fn):
                            res = await self.executor_fn(
                                tool_use,
                                caller_role=caller_role,
                                sandbox_limits=sandbox_limits,
                                username=username,
                                sandbox_id=sandbox_id
                            )
                        else:
                            res = self.executor_fn(
                                tool_use,
                                caller_role=caller_role,
                                sandbox_limits=sandbox_limits,
                                username=username,
                                sandbox_id=sandbox_id
                            )
                    except TypeError:
                        # Fallback for simple executor signatures in unit tests
                        if asyncio.iscoroutinefunction(self.executor_fn):
                            res = await self.executor_fn(payload)
                        else:
                            res = self.executor_fn(payload)
                    task.status = "completed"
                    task.result = res
                    self._total_completed += 1
                except Exception as e:
                    logger.error(f"Fallback local execution failed: {e}")
                    task.status = "failed"
                    task.result = {"is_error": True, "content": str(e)}
                    self._total_failed += 1
            return task

    def get_status(self) -> dict:
        """Return metrics and connection status."""
        status = {
            "total_submitted": self._total_submitted,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
        }
        if self.broker:
            status.update(self.broker.get_status())
        else:
            status["connected"] = False
        return status
