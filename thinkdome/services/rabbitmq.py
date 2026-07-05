"""Production RabbitMQ task broker for distributed sandbox orchestration.

Replaces the in-memory partition scheduler with a durable, distributed
message queue that survives pod restarts and supports horizontal scaling.

Architecture:
  - Durable exchanges and queues with publisher confirms
  - Dead-letter exchange (sandbox.dlx) for failed tasks with retry
  - Priority queues (0-9) for SRSF-equivalent deadline ordering
  - RPC pattern: publish request → wait on reply queue → return result
  - Circuit breaker for downstream failure protection
  - Automatic reconnection with exponential backoff

Queue topology:
  sandbox.execute     — code execution tasks (priority queue)
  sandbox.file_ops    — file operation tasks
  sandbox.admin       — admin/lifecycle tasks
  sandbox.results     — RPC reply queue (per-consumer exclusive)
  sandbox.dlx         — dead-letter exchange for retries
  sandbox.retry       — retry queue with TTL-based redelivery
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

import aio_pika
from aio_pika import (
    Channel,
    Connection,
    DeliveryMode,
    ExchangeType,
    Message,
    connect_robust,
)
from aio_pika.abc import AbstractIncomingMessage

logger = logging.getLogger(__name__)


# ── Message Schema ──────────────────────────────────────────────────────────────

@dataclass
class TaskMessage:
    """Structured task message published to RabbitMQ."""
    task_id: str
    tool_use: Dict[str, Any]
    caller_role: str = "LLM"
    username: Optional[str] = None
    sandbox_id: Optional[str] = None
    sandbox_limits: Optional[Dict[str, Any]] = None
    deadline_ms: float = 10000
    priority: int = 5          # 0 (lowest) to 9 (highest)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    submitted_at: float = field(default_factory=time.time)

    def to_json(self) -> bytes:
        return json.dumps({
            "task_id": self.task_id,
            "tool_use": self.tool_use,
            "caller_role": self.caller_role,
            "username": self.username,
            "sandbox_id": self.sandbox_id,
            "sandbox_limits": self.sandbox_limits,
            "deadline_ms": self.deadline_ms,
            "priority": self.priority,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "submitted_at": self.submitted_at,
        }).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> "TaskMessage":
        d = json.loads(data)
        return cls(**d)


@dataclass
class TaskResult:
    """Result message returned from a worker."""
    task_id: str
    result: Dict[str, Any]
    is_error: bool = False
    duration_ms: float = 0.0
    worker_id: Optional[str] = None
    trace_id: Optional[str] = None

    def to_json(self) -> bytes:
        return json.dumps({
            "task_id": self.task_id,
            "result": self.result,
            "is_error": self.is_error,
            "duration_ms": self.duration_ms,
            "worker_id": self.worker_id,
            "trace_id": self.trace_id,
        }).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> "TaskResult":
        d = json.loads(data)
        return cls(**d)


# ── Circuit Breaker ─────────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Simple circuit breaker for downstream failure protection."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 30.0,
        name: str = "default",
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._success_count_in_half_open = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout_sec:
                self._state = CircuitState.HALF_OPEN
                self._success_count_in_half_open = 0
                logger.info(f"Circuit breaker '{self.name}' → HALF_OPEN")
        return self._state

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count_in_half_open += 1
            if self._success_count_in_half_open >= 2:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(f"Circuit breaker '{self.name}' → CLOSED (recovered)")
        else:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker '{self.name}' → OPEN "
                f"(failures={self._failure_count})"
            )

    def allow_request(self) -> bool:
        state = self.state  # Triggers time-based transition
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True
        return False


# ── Task Broker ─────────────────────────────────────────────────────────────────

class TaskBroker:
    """Production RabbitMQ task broker with durable queues and RPC support.

    Usage:
        broker = TaskBroker(rabbitmq_url="amqp://guest:guest@localhost:5672/")
        await broker.start()

        # Publish and wait for result (RPC)
        result = await broker.publish_and_wait(task_message, timeout=30.0)

        # Or publish fire-and-forget
        await broker.publish(task_message)

        await broker.stop()
    """

    # Queue names
    EXCHANGE_NAME = "sandbox"
    EXECUTE_QUEUE = "sandbox.execute"
    FILE_OPS_QUEUE = "sandbox.file_ops"
    ADMIN_QUEUE = "sandbox.admin"
    DLX_EXCHANGE = "sandbox.dlx"
    RETRY_QUEUE = "sandbox.retry"

    # Queue routing keys
    ROUTING_KEYS = {
        "run_code": "execute",
        "shell_exec": "execute",
        "read_file": "file_ops",
        "write_file": "file_ops",
        "list_dir": "file_ops",
        "file_exists": "file_ops",
        "make_dir": "file_ops",
        "remove_file": "file_ops",
        "remove_dir": "file_ops",
        "move_file": "file_ops",
        "copy_file": "file_ops",
        "grep_search": "file_ops",
        "find_files": "file_ops",
        "get_file_info": "file_ops",
        "hash_file": "file_ops",
    }

    def __init__(
        self,
        rabbitmq_url: str = "amqp://guest:guest@localhost:5672/",
        prefetch_count: int = 10,
    ) -> None:
        self._url = rabbitmq_url
        self._prefetch_count = prefetch_count
        self._connection: Optional[Connection] = None
        self._channel: Optional[Channel] = None
        self._callback_queue: Optional[aio_pika.abc.AbstractQueue] = None
        self._futures: Dict[str, asyncio.Future] = {}
        self._circuit_breaker = CircuitBreaker(name="rabbitmq")

        # Metrics
        self._total_published: int = 0
        self._total_consumed: int = 0
        self._total_errors: int = 0

    async def start(self) -> None:
        """Connect to RabbitMQ and declare topology."""
        logger.info(f"🐰 Connecting to RabbitMQ: {self._url.split('@')[-1]}")

        self._connection = await connect_robust(
            self._url,
            heartbeat=60,
            blocked_connection_timeout=30,
        )

        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._prefetch_count)

        # Declare main exchange (topic type for flexible routing)
        exchange = await self._channel.declare_exchange(
            self.EXCHANGE_NAME,
            ExchangeType.TOPIC,
            durable=True,
        )

        # Declare dead-letter exchange
        dlx_exchange = await self._channel.declare_exchange(
            self.DLX_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )

        # Declare retry queue with TTL → redelivery to main exchange
        retry_queue = await self._channel.declare_queue(
            self.RETRY_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.EXCHANGE_NAME,
                "x-message-ttl": 5000,  # 5s before retry
            },
        )
        await retry_queue.bind(dlx_exchange, routing_key="retry")

        # Declare main task queues with DLX routing and priority support
        for queue_name, routing_key in [
            (self.EXECUTE_QUEUE, "execute"),
            (self.FILE_OPS_QUEUE, "file_ops"),
            (self.ADMIN_QUEUE, "admin"),
        ]:
            queue = await self._channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": self.DLX_EXCHANGE,
                    "x-dead-letter-routing-key": "retry",
                    "x-max-priority": 10,  # Priority queue support
                },
            )
            await queue.bind(exchange, routing_key=routing_key)

        # Declare exclusive callback queue for RPC responses
        self._callback_queue = await self._channel.declare_queue(
            exclusive=True,
        )
        await self._callback_queue.consume(self._on_response)

        logger.info(
            f"🐰 RabbitMQ connected. Queues: {self.EXECUTE_QUEUE}, "
            f"{self.FILE_OPS_QUEUE}, {self.ADMIN_QUEUE}"
        )

    async def stop(self) -> None:
        """Close RabbitMQ connection gracefully."""
        # Cancel pending futures
        for future in self._futures.values():
            if not future.done():
                future.cancel()
        self._futures.clear()

        if self._connection and not self._connection.is_closed:
            await self._connection.close()

        logger.info("🐰 RabbitMQ connection closed")

    # ── Publishing ──────────────────────────────────────────────────────────────

    def _get_routing_key(self, tool_name: str) -> str:
        """Determine which queue a task should go to based on tool name."""
        return self.ROUTING_KEYS.get(tool_name, "execute")

    async def publish(self, task: TaskMessage) -> None:
        """Publish a task message (fire-and-forget)."""
        if not self._circuit_breaker.allow_request():
            raise ConnectionError(
                "Circuit breaker OPEN: RabbitMQ is unavailable"
            )

        try:
            exchange = await self._channel.get_exchange(self.EXCHANGE_NAME)
            routing_key = self._get_routing_key(
                task.tool_use.get("name", "run_code")
            )

            message = Message(
                body=task.to_json(),
                delivery_mode=DeliveryMode.PERSISTENT,
                priority=task.priority,
                message_id=task.task_id,
                headers={
                    "trace_id": task.trace_id or "",
                    "span_id": task.span_id or "",
                    "retry_count": str(task.retry_count),
                    "max_retries": str(task.max_retries),
                },
                expiration=int(task.deadline_ms),
            )

            await exchange.publish(message, routing_key=routing_key)
            self._total_published += 1
            self._circuit_breaker.record_success()

            logger.debug(
                f"📤 Published task {task.task_id} → {routing_key} "
                f"(priority={task.priority})"
            )

        except Exception as e:
            self._total_errors += 1
            self._circuit_breaker.record_failure()
            logger.error(f"Failed to publish task {task.task_id}: {e}")
            raise

    async def publish_and_wait(
        self,
        task: TaskMessage,
        timeout: float = 30.0,
    ) -> TaskResult:
        """Publish a task and wait for the worker result (RPC pattern).

        Uses an exclusive callback queue and correlation_id to match
        responses to requests.
        """
        if not self._circuit_breaker.allow_request():
            raise ConnectionError(
                "Circuit breaker OPEN: RabbitMQ is unavailable"
            )

        correlation_id = task.task_id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._futures[correlation_id] = future

        try:
            exchange = await self._channel.get_exchange(self.EXCHANGE_NAME)
            routing_key = self._get_routing_key(
                task.tool_use.get("name", "run_code")
            )

            message = Message(
                body=task.to_json(),
                delivery_mode=DeliveryMode.PERSISTENT,
                priority=task.priority,
                message_id=task.task_id,
                correlation_id=correlation_id,
                reply_to=self._callback_queue.name,
                headers={
                    "trace_id": task.trace_id or "",
                    "span_id": task.span_id or "",
                    "retry_count": str(task.retry_count),
                    "max_retries": str(task.max_retries),
                },
                expiration=int(task.deadline_ms),
            )

            await exchange.publish(message, routing_key=routing_key)
            self._total_published += 1

            logger.debug(
                f"📤 Published RPC task {task.task_id} → {routing_key} "
                f"(timeout={timeout}s)"
            )

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            self._circuit_breaker.record_success()
            return result

        except asyncio.TimeoutError:
            self._total_errors += 1
            logger.warning(f"⏰ RPC timeout for task {task.task_id}")
            return TaskResult(
                task_id=task.task_id,
                result={"error": f"Task timed out after {timeout}s"},
                is_error=True,
            )
        except Exception as e:
            self._total_errors += 1
            self._circuit_breaker.record_failure()
            logger.error(f"RPC publish failed for task {task.task_id}: {e}")
            raise
        finally:
            self._futures.pop(correlation_id, None)

    async def _on_response(self, message: AbstractIncomingMessage) -> None:
        """Handle incoming RPC response messages on the callback queue."""
        async with message.process():
            correlation_id = message.correlation_id
            if correlation_id and correlation_id in self._futures:
                try:
                    result = TaskResult.from_json(message.body)
                    future = self._futures.get(correlation_id)
                    if future and not future.done():
                        future.set_result(result)
                        self._total_consumed += 1
                except Exception as e:
                    logger.error(f"Failed to parse RPC response: {e}")

    # ── Consumer Registration ───────────────────────────────────────────────────

    async def consume(
        self,
        queue_name: str,
        callback: Callable,
    ) -> None:
        """Register a consumer callback for a specific queue.

        The callback receives (TaskMessage, Channel, AbstractIncomingMessage)
        and must ack/nack the message.
        """
        queue = await self._channel.get_queue(queue_name)
        await queue.consume(
            lambda msg: self._dispatch_consumer(msg, callback)
        )
        logger.info(f"🔊 Consuming from {queue_name}")

    async def _dispatch_consumer(
        self,
        message: AbstractIncomingMessage,
        callback: Callable,
    ) -> None:
        """Parse incoming message and dispatch to the registered callback."""
        try:
            task = TaskMessage.from_json(message.body)
            await callback(task, self._channel, message)
        except Exception as e:
            logger.error(f"Consumer dispatch error: {e}")
            # Nack and let DLX handle retry
            await message.nack(requeue=False)

    # ── Metrics ─────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return broker-wide metrics."""
        return {
            "connected": (
                self._connection is not None
                and not self._connection.is_closed
            ),
            "circuit_breaker": self._circuit_breaker.state.value,
            "total_published": self._total_published,
            "total_consumed": self._total_consumed,
            "total_errors": self._total_errors,
            "pending_rpcs": len(self._futures),
        }
