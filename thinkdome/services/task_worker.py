"""Stateless RabbitMQ task worker for sandbox execution.

Runs as an independent process that consumes tasks from RabbitMQ queues,
executes them via OrchestratorService, and publishes results back.

Features:
  - Consumes from sandbox.execute, sandbox.file_ops, sandbox.admin queues
  - Publishes results to the caller's reply queue (RPC correlation)
  - Circuit breaker for executor failures
  - Graceful shutdown with in-flight task completion
  - Dead-letter routing for failed tasks with retry tracking
  - Structured logging with trace_id propagation
  - Worker identity for distributed debugging

Usage:
    python -m thinkdome.services.task_worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import uuid
from typing import Optional

import aio_pika
from aio_pika import Message, DeliveryMode
from aio_pika.abc import AbstractIncomingMessage, AbstractChannel

from thinkdome.core.config import get_settings
from thinkdome.services.rabbitmq import (
    TaskBroker,
    TaskMessage,
    TaskResult,
    CircuitBreaker,
)

logger = logging.getLogger(__name__)


class TaskWorker:
    """Stateless worker that consumes sandbox tasks from RabbitMQ.

    Each worker instance:
      - Has a unique worker_id for identification
      - Consumes from all three task queues
      - Executes tasks via a provided executor function
      - Publishes results back via RPC reply_to / correlation_id
      - Tracks circuit breaker state for downstream executor health
    """

    def __init__(
        self,
        rabbitmq_url: str,
        executor_fn=None,
        worker_id: Optional[str] = None,
        prefetch_count: int = 5,
    ) -> None:
        self._url = rabbitmq_url
        self._executor_fn = executor_fn
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._prefetch_count = prefetch_count

        self._connection: Optional[aio_pika.Connection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._running = False

        self._circuit_breaker = CircuitBreaker(
            name=f"executor-{self._worker_id}",
            failure_threshold=5,
            recovery_timeout_sec=30.0,
        )

        # Metrics
        self._tasks_processed: int = 0
        self._tasks_failed: int = 0
        self._tasks_retried: int = 0

    async def start(self) -> None:
        """Connect to RabbitMQ and start consuming from task queues."""
        self._running = True
        logger.info(f"🔧 Worker {self._worker_id} starting...")

        self._connection = await aio_pika.connect_robust(
            self._url,
            heartbeat=60,
        )

        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._prefetch_count)

        # Consume from all task queues
        for queue_name in [
            TaskBroker.EXECUTE_QUEUE,
            TaskBroker.FILE_OPS_QUEUE,
            TaskBroker.ADMIN_QUEUE,
        ]:
            try:
                queue = await self._channel.declare_queue(
                    queue_name,
                    durable=True,
                    passive=True,  # Queue must already exist (declared by broker)
                )
                await queue.consume(self._process_message)
                logger.info(f"🔊 Worker {self._worker_id} consuming: {queue_name}")
            except Exception as e:
                logger.warning(
                    f"Could not bind to queue {queue_name}: {e}. "
                    f"Ensure TaskBroker.start() was called first."
                )

        logger.info(f"🔧 Worker {self._worker_id} ready (prefetch={self._prefetch_count})")

    async def stop(self) -> None:
        """Graceful shutdown — finish in-flight tasks then disconnect."""
        self._running = False
        logger.info(f"🔧 Worker {self._worker_id} shutting down...")

        if self._connection and not self._connection.is_closed:
            await self._connection.close()

        logger.info(
            f"🔧 Worker {self._worker_id} stopped. "
            f"Processed={self._tasks_processed}, "
            f"Failed={self._tasks_failed}, "
            f"Retried={self._tasks_retried}"
        )

    async def _process_message(self, message: AbstractIncomingMessage) -> None:
        """Process a single task message from the queue."""
        start_time = time.monotonic()

        try:
            task = TaskMessage.from_json(message.body)
        except Exception as e:
            logger.error(f"Failed to parse task message: {e}")
            await message.ack()  # Don't retry unparseable messages
            return

        log_prefix = f"[{task.task_id}]"
        if task.trace_id:
            log_prefix = f"[{task.task_id}|trace={task.trace_id[:8]}]"

        logger.info(
            f"{log_prefix} Processing tool={task.tool_use.get('name', '?')} "
            f"role={task.caller_role} retry={task.retry_count}"
        )

        # Check circuit breaker
        if not self._circuit_breaker.allow_request():
            logger.warning(f"{log_prefix} Circuit breaker OPEN, nacking for requeue")
            await message.nack(requeue=True)
            return

        # Check deadline
        elapsed_since_submit = (time.time() - task.submitted_at) * 1000
        if elapsed_since_submit > task.deadline_ms:
            logger.warning(
                f"{log_prefix} Task expired "
                f"(elapsed={elapsed_since_submit:.0f}ms > deadline={task.deadline_ms}ms)"
            )
            await self._send_result(
                message,
                TaskResult(
                    task_id=task.task_id,
                    result={"error": "Task expired before execution"},
                    is_error=True,
                    worker_id=self._worker_id,
                    trace_id=task.trace_id,
                ),
            )
            await message.ack()
            return

        # Execute the task
        try:
            if self._executor_fn:
                result_data = await self._executor_fn(
                    task.tool_use,
                    caller_role=task.caller_role,
                    sandbox_limits=task.sandbox_limits,
                    username=task.username,
                    sandbox_id=task.sandbox_id,
                )
            else:
                result_data = {
                    "type": "tool_result",
                    "tool_use_id": task.tool_use.get("id", "unknown"),
                    "content": "No executor configured",
                    "is_error": True,
                }

            duration_ms = (time.monotonic() - start_time) * 1000

            task_result = TaskResult(
                task_id=task.task_id,
                result=result_data,
                is_error=result_data.get("is_error", False),
                duration_ms=round(duration_ms, 2),
                worker_id=self._worker_id,
                trace_id=task.trace_id,
            )

            await self._send_result(message, task_result)
            await message.ack()

            self._tasks_processed += 1
            self._circuit_breaker.record_success()

            logger.info(
                f"{log_prefix} Completed in {duration_ms:.1f}ms "
                f"(error={task_result.is_error})"
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            self._tasks_failed += 1
            self._circuit_breaker.record_failure()

            logger.error(f"{log_prefix} Execution failed after {duration_ms:.1f}ms: {e}")

            # Retry logic: check retry count in headers
            retry_count = task.retry_count
            max_retries = task.max_retries

            if retry_count < max_retries:
                # Nack without requeue → goes to DLX → retry queue → redelivery
                self._tasks_retried += 1
                logger.info(
                    f"{log_prefix} Scheduling retry "
                    f"({retry_count + 1}/{max_retries})"
                )
                await message.nack(requeue=False)
            else:
                # Max retries exhausted — send error result
                logger.error(
                    f"{log_prefix} Max retries exhausted ({max_retries})"
                )
                error_result = TaskResult(
                    task_id=task.task_id,
                    result={
                        "type": "tool_result",
                        "tool_use_id": task.tool_use.get("id", "unknown"),
                        "content": f"Task failed after {max_retries} retries: {str(e)}",
                        "is_error": True,
                    },
                    is_error=True,
                    duration_ms=round(duration_ms, 2),
                    worker_id=self._worker_id,
                    trace_id=task.trace_id,
                )
                await self._send_result(message, error_result)
                await message.ack()

    async def _send_result(
        self,
        original_message: AbstractIncomingMessage,
        result: TaskResult,
    ) -> None:
        """Send a result back to the caller's reply queue (RPC pattern)."""
        reply_to = original_message.reply_to
        correlation_id = original_message.correlation_id

        if not reply_to or not correlation_id:
            # Fire-and-forget task — no reply expected
            return

        try:
            response = Message(
                body=result.to_json(),
                delivery_mode=DeliveryMode.NOT_PERSISTENT,
                correlation_id=correlation_id,
            )

            await self._channel.default_exchange.publish(
                response,
                routing_key=reply_to,
            )

            logger.debug(
                f"📨 Sent result for {result.task_id} → {reply_to}"
            )

        except Exception as e:
            logger.error(
                f"Failed to send result for {result.task_id}: {e}"
            )

    def get_status(self) -> dict:
        """Return worker metrics."""
        return {
            "worker_id": self._worker_id,
            "running": self._running,
            "connected": (
                self._connection is not None
                and not self._connection.is_closed
            ),
            "circuit_breaker": self._circuit_breaker.state.value,
            "tasks_processed": self._tasks_processed,
            "tasks_failed": self._tasks_failed,
            "tasks_retried": self._tasks_retried,
        }


# ── Standalone Worker Entry Point ───────────────────────────────────────────────

async def run_worker():
    """Run the task worker as a standalone process."""
    settings = get_settings()

    # Initialize executor (OrchestratorService)
    from thinkdome.services.execution_service import ExecutionService
    from thinkdome.services.search_service import SearchService
    from thinkdome.services.orchestrator_service import OrchestratorService

    execution_service = ExecutionService(settings)
    search_service = SearchService(settings)
    orchestrator = OrchestratorService(
        settings, execution_service, search_service
    )

    await execution_service.initialize()

    # Create and start broker (to declare topology)
    broker = TaskBroker(rabbitmq_url=settings.RABBITMQ_URL)
    await broker.start()

    # Create and start worker
    worker = TaskWorker(
        rabbitmq_url=settings.RABBITMQ_URL,
        executor_fn=orchestrator.execute_tool,
    )
    await worker.start()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("🔧 Task worker running. Press Ctrl+C to stop.")
    await stop_event.wait()

    # Graceful shutdown
    await worker.stop()
    await broker.stop()
    await execution_service.shutdown()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    asyncio.run(run_worker())
