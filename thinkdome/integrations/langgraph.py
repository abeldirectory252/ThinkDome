"""LangGraph-compatible adapters for ThinkDome sandbox execution.

The integration is intentionally optional: importing ThinkDome does not
require LangGraph.  Adapters use ordinary async callables and can be passed
to LangGraph nodes/tools directly; when LangGraph is installed, ``thinkdome_tool``
returns a native ``BaseTool`` instance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import inspect
import re
import sqlite3
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

from thinkdome.sandbox.sdk import Sandbox, SandboxResult
try:
    from thinkdome.core.orm.orm import Model, StringField, FloatField, IntegerField
    _ORM_AVAILABLE = True
except ImportError:  # optional integration remains importable before dependencies are installed
    _ORM_AVAILABLE = False
    class Model:  # type: ignore[no-redef]
        pass
    def StringField(**kwargs): return None  # type: ignore[misc]
    def FloatField(**kwargs): return None  # type: ignore[misc]
    def IntegerField(**kwargs): return None  # type: ignore[misc]


class LangGraphCheckpointRecord(Model):
    """ORM record for one LangGraph checkpoint and its lineage."""

    thread_id = StringField(required=True)
    checkpoint_ns = StringField(default="")
    checkpoint_id = StringField(required=True)
    parent_id = StringField(default="")
    checkpoint_payload = StringField(required=True)
    metadata_payload = StringField(required=True)
    created_at = FloatField(default=0.0)
    __unique_together__ = ("thread_id", "checkpoint_ns", "checkpoint_id")


class LangGraphWriteRecord(Model):
    """ORM record for pending LangGraph task writes."""

    thread_id = StringField(required=True)
    checkpoint_ns = StringField(default="")
    checkpoint_id = StringField(required=True)
    task_id = StringField(required=True)
    write_index = IntegerField(required=True)
    channel = StringField(required=True)
    value_payload = StringField(required=True)
    __unique_together__ = ("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "write_index")

try:  # Optional native LangGraph runtime
    from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
except ImportError:  # pragma: no cover - exercised when optional extra is absent
    class BaseCheckpointSaver:  # type: ignore[no-redef]
        pass

    @dataclass(frozen=True)
    class CheckpointTuple:  # type: ignore[no-redef]
        config: Mapping[str, Any]
        checkpoint: Any
        metadata: Mapping[str, Any]
        parent_config: Mapping[str, Any] | None
        pending_writes: list[tuple[str, str, Any]]


class LangGraphIntegrationError(RuntimeError):
    """Raised when an optional LangGraph adapter cannot be initialized."""


def _result_dict(result: SandboxResult) -> dict[str, Any]:
    return {
        "output": result.output,
        "error": result.error,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "duration_ms": result.duration_ms,
        "files": result.files,
        "error_code": result.error_code,
    }


@dataclass
class ThinkDomeSandboxNode:
    """Execute a LangGraph node body inside one owned ThinkDome sandbox.

    The sandbox is created lazily, reused only by this node instance, and
    closed explicitly via ``aclose``.  Concurrent calls are serialized to
    prevent state and workspace mixing within a graph run.
    """

    sandbox: Sandbox
    code_builder: Callable[[Mapping[str, Any]], str]
    state_key: str = "thinkdome"
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._lock = asyncio.Lock()
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise LangGraphIntegrationError("ThinkDome sandbox node is closed")

    async def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._ensure_open()
            code = self.code_builder(state)
            if inspect.isawaitable(code):
                code = await code
            if not isinstance(code, str) or not code:
                raise LangGraphIntegrationError("Sandbox node code_builder must return non-empty source")
            execution = self.sandbox.arun(code)
            try:
                result = (
                    await asyncio.wait_for(execution, timeout=self.timeout_seconds)
                    if self.timeout_seconds is not None
                    else await execution
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                await self.sandbox.__aexit__(type(exc), exc, exc.__traceback__)
                self._closed = True
                raise
            payload = _result_dict(result)
            if not result.success:
                raise LangGraphIntegrationError(
                    f"ThinkDome sandbox node failed: {result.error_code or 'execution_failed'}"
                )
            return {self.state_key: payload}

    async def checkpoint(self, tag: str = "langgraph") -> str:
        async with self._lock:
            self._ensure_open()
            return await asyncio.to_thread(self.sandbox.snapshot, tag=tag)

    async def restore(self, snapshot_id: str) -> None:
        async with self._lock:
            self._ensure_open()
            restored = await asyncio.to_thread(self.sandbox.restore, snapshot_id)
            if not restored:
                raise LangGraphIntegrationError(f"Unable to restore ThinkDome snapshot {snapshot_id}")

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await self.sandbox.__aexit__(None, None, None)
            self._closed = True


class ThinkDomeCheckpointStore:
    """Small async checkpoint store backed by ThinkDome sandbox snapshots."""

    def __init__(
        self,
        node: ThinkDomeSandboxNode,
        *,
        tenant_id: str = "default",
        thread_id: str = "default",
    ) -> None:
        self.node = node
        self.tenant_id = self._validate_scope(tenant_id, "tenant_id")
        self.thread_id = self._validate_scope(thread_id, "thread_id")
        self._metadata: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _validate_scope(value: str, name: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
            raise LangGraphIntegrationError(f"{name} must be 1-128 safe characters")
        return value

    def _scoped_tag(self, checkpoint_id: str) -> str:
        return f"{self.tenant_id}:{self.thread_id}:{checkpoint_id}"

    @staticmethod
    def _validate_checkpoint_id(checkpoint_id: str) -> str:
        if not isinstance(checkpoint_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", checkpoint_id):
            raise LangGraphIntegrationError("Checkpoint ID must be 1-128 safe characters")
        return checkpoint_id

    async def _hydrate(self, checkpoint_id: str) -> Optional[dict[str, Any]]:
        """Recover a checkpoint mapping from persisted snapshot metadata."""
        for snapshot in await asyncio.to_thread(self.node.sandbox.list_snapshots):
            if snapshot.get("tag") == self._scoped_tag(checkpoint_id):
                value = {"snapshot_id": snapshot["snapshot_id"], "tag": checkpoint_id,
                         "tenant_id": self.tenant_id, "thread_id": self.thread_id}
                self._metadata[checkpoint_id] = value
                return value
        return None

    async def put(self, checkpoint_id: str, metadata: Optional[Mapping[str, Any]] = None) -> str:
        checkpoint_id = self._validate_checkpoint_id(checkpoint_id)
        async with self._lock:
            previous = self._metadata.get(checkpoint_id)
            snapshot_id = await self.node.checkpoint(tag=self._scoped_tag(checkpoint_id))
            self._metadata[checkpoint_id] = {
                "snapshot_id": snapshot_id,
                "tag": checkpoint_id,
                "tenant_id": self.tenant_id,
                "thread_id": self.thread_id,
                **dict(metadata or {}),
            }
            if previous and previous.get("snapshot_id") != snapshot_id:
                await asyncio.to_thread(
                    self.node.sandbox.snapshot_service.delete_snapshot,
                    str(previous["snapshot_id"]),
                )
            return snapshot_id

    async def get(self, checkpoint_id: str) -> Optional[dict[str, Any]]:
        checkpoint_id = self._validate_checkpoint_id(checkpoint_id)
        async with self._lock:
            value = self._metadata.get(checkpoint_id)
            if value is None:
                value = await self._hydrate(checkpoint_id)
            return dict(value) if value else None

    async def restore(self, checkpoint_id: str) -> None:
        checkpoint_id = self._validate_checkpoint_id(checkpoint_id)
        async with self._lock:
            value = self._metadata.get(checkpoint_id)
            if value is None:
                value = await self._hydrate(checkpoint_id)
            if not value:
                raise LangGraphIntegrationError(f"Unknown ThinkDome checkpoint {checkpoint_id}")
            await self.node.restore(str(value["snapshot_id"]))

    async def list(self) -> list[dict[str, Any]]:
        """Return checkpoint metadata in deterministic insertion order."""
        async with self._lock:
            for snapshot in await asyncio.to_thread(self.node.sandbox.list_snapshots):
                tag = snapshot.get("tag")
                prefix = f"{self.tenant_id}:{self.thread_id}:"
                if isinstance(tag, str) and tag.startswith(prefix):
                    checkpoint_id = tag[len(prefix):]
                    if checkpoint_id not in self._metadata:
                        self._metadata[checkpoint_id] = {
                            "snapshot_id": snapshot["snapshot_id"],
                            "tag": checkpoint_id,
                            "tenant_id": self.tenant_id,
                            "thread_id": self.thread_id,
                        }
            return [dict(value, checkpoint_id=key) for key, value in self._metadata.items()]

    async def delete(self, checkpoint_id: str) -> None:
        checkpoint_id = self._validate_checkpoint_id(checkpoint_id)
        async with self._lock:
            value = self._metadata.get(checkpoint_id)
            if not value:
                return
            snapshot_id = str(value["snapshot_id"])
            deleted = await asyncio.to_thread(
                self.node.sandbox.snapshot_service.delete_snapshot,
                snapshot_id,
            )
            if not deleted:
                raise LangGraphIntegrationError(
                    f"Unable to delete ThinkDome snapshot {snapshot_id}"
                )
            self._metadata.pop(checkpoint_id, None)


class ThinkDomeLangGraphCheckpointer(BaseCheckpointSaver):
    """ORM-compatible native LangGraph checkpointer with Redis support.

    Redis is the recommended backend for multi-worker deployments. The local
    SQLite compatibility backend remains available for development and tests;
    it is never selected when ``redis_url`` or ``redis_client`` is provided.
    """

    def __init__(
        self,
        path: str = "./storage/langgraph/checkpoints.sqlite3",
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        redis_prefix: str = "thinkdome:langgraph",
    ) -> None:
        if not isinstance(path, str) or not path:
            raise LangGraphIntegrationError("Checkpoint database path is required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._serializer = None
        try:
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
            self._serializer = JsonPlusSerializer()
        except ImportError:
            pass
        try:
            super().__init__(serde=self._serializer)
        except TypeError:  # fallback shim when LangGraph is not installed
            super().__init__()
        self._sync_lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self._redis = redis_client
        if redis_url and redis_client is not None:
            raise LangGraphIntegrationError("Specify redis_url or redis_client, not both")
        if redis_url:
            try:
                import redis
                self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
            except ImportError as exc:
                raise LangGraphIntegrationError("Redis support requires the redis package") from exc
        self._redis_prefix = redis_prefix.rstrip(":")
        self._orm = self._resolve_orm()
        if self._orm:
            self._ensure_orm_schema()
        elif not self._redis:
            self._init_db()

    @staticmethod
    def _resolve_orm() -> bool:
        """Use the active ThinkDome ORM when the application kernel is ready."""
        if not _ORM_AVAILABLE:
            return False
        try:
            from thinkdome.core.kernel.kernel import Kernel
            kernel = Kernel.current()
            return bool(kernel.initialized and kernel.db is not None)
        except (FileNotFoundError, RuntimeError, ValueError):
            return False

    @staticmethod
    def _ensure_orm_schema() -> None:
        from thinkdome.core.kernel.kernel import Kernel
        from thinkdome.core.orm.orm import Base
        Base.metadata.create_all(Kernel.current().db_engine)

    @property
    def uses_redis(self) -> bool:
        return self._redis is not None

    def _redis_scope_key(self, thread_id: str, namespace: str) -> str:
        encoded_thread = base64.urlsafe_b64encode(thread_id.encode()).decode().rstrip("=")
        encoded_namespace = base64.urlsafe_b64encode(namespace.encode()).decode().rstrip("=")
        return f"{self._redis_prefix}:index:{encoded_thread}:{encoded_namespace}"

    def _redis_checkpoint_key(self, thread_id: str, namespace: str, checkpoint_id: str) -> str:
        encoded_thread = base64.urlsafe_b64encode(thread_id.encode()).decode().rstrip("=")
        encoded_namespace = base64.urlsafe_b64encode(namespace.encode()).decode().rstrip("=")
        encoded_checkpoint = base64.urlsafe_b64encode(checkpoint_id.encode()).decode().rstrip("=")
        return f"{self._redis_prefix}:checkpoint:{encoded_thread}:{encoded_namespace}:{encoded_checkpoint}"

    def _redis_write_key(self, thread_id: str, namespace: str, checkpoint_id: str) -> str:
        encoded = [base64.urlsafe_b64encode(value.encode()).decode().rstrip("=") for value in (thread_id, namespace, checkpoint_id)]
        return f"{self._redis_prefix}:writes:{':'.join(encoded)}"

    def _cache_checkpoint(self, thread_id: str, namespace: str, checkpoint_id: str, parent_id: str | None, checkpoint: bytes, metadata: bytes) -> None:
        """Write-through cache; the ORM remains authoritative."""
        payload = json.dumps({"parent_id": parent_id, "checkpoint": checkpoint.decode(), "metadata": metadata.decode()})
        pipe = self._redis.pipeline(transaction=True)
        pipe.set(self._redis_checkpoint_key(thread_id, namespace, checkpoint_id), payload)
        pipe.zadd(self._redis_scope_key(thread_id, namespace), {checkpoint_id: time.time_ns()})
        pipe.execute()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as db:
            # WAL permits readers during writes and is durable for a local
            # checkpointer.  Every operation below also sets busy_timeout so
            # concurrent graph workers fail predictably instead of spinning.
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL, checkpoint_id TEXT NOT NULL, parent_id TEXT, checkpoint BLOB NOT NULL, metadata BLOB NOT NULL, PRIMARY KEY(thread_id, checkpoint_ns, checkpoint_id))")
            db.execute("CREATE TABLE IF NOT EXISTS writes (thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL, checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, channel TEXT NOT NULL, value BLOB NOT NULL, PRIMARY KEY(thread_id, checkpoint_ns, checkpoint_id, task_id, idx))")
            db.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_scope ON checkpoints(thread_id, checkpoint_ns)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_writes_scope ON writes(thread_id, checkpoint_ns, checkpoint_id)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _encode(self, value: Any) -> bytes:
        if self._serializer is not None:
            type_tag, payload = self._serializer.dumps_typed(value)
            return json.dumps({"type": type_tag, "data": base64.b64encode(payload).decode()}).encode()
        return json.dumps(value, separators=(",", ":")).encode()

    def _decode(self, value: bytes) -> Any:
        record = json.loads(value)
        if self._serializer is not None and isinstance(record, dict) and "type" in record:
            return self._serializer.loads_typed((record["type"], base64.b64decode(record["data"])))
        return record

    @staticmethod
    def _scope(config: Mapping[str, Any]) -> tuple[str, str, str | None]:
        configurable = config.get("configurable", config)
        thread_id = configurable.get("thread_id")
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")
        if not isinstance(thread_id, str) or not 1 <= len(thread_id) <= 512 or any(ord(char) < 32 for char in thread_id):
            raise LangGraphIntegrationError("LangGraph configurable.thread_id must be 1-512 printable characters")
        if not isinstance(namespace, str) or len(namespace) > 512 or any(ord(char) < 32 for char in namespace):
            raise LangGraphIntegrationError("LangGraph configurable.checkpoint_ns must be at most 512 printable characters")
        if checkpoint_id is not None and (not isinstance(checkpoint_id, str) or len(checkpoint_id) > 512 or any(ord(char) < 32 for char in checkpoint_id)):
            raise LangGraphIntegrationError("LangGraph configurable.checkpoint_id must be at most 512 printable characters")
        return thread_id, namespace, checkpoint_id

    async def aput(self, config: Mapping[str, Any], checkpoint: Any, metadata: Mapping[str, Any], new_versions: Mapping[str, Any]) -> dict[str, Any]:
        thread_id, namespace, _ = self._scope(config)
        checkpoint_id = str(checkpoint.get("id") or metadata.get("checkpoint_id"))
        parent_id = (config.get("configurable", config) or {}).get("checkpoint_id")
        if not checkpoint_id or checkpoint_id == "None":
            raise LangGraphIntegrationError("Checkpoint must contain an id")
        encoded_checkpoint = self._encode(checkpoint)
        encoded_metadata = self._encode(dict(metadata))
        async with self._async_lock:
            self._put_row(thread_id, namespace, checkpoint_id, parent_id, encoded_checkpoint, encoded_metadata)
        return {**dict(config), "configurable": {**dict(config.get("configurable", {})), "checkpoint_id": checkpoint_id}}

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id, namespace, _ = self._scope(config)
        checkpoint_id = str(checkpoint.get("id") or metadata.get("checkpoint_id"))
        parent_id = (config.get("configurable", config) or {}).get("checkpoint_id")
        if not checkpoint_id or checkpoint_id == "None":
            raise LangGraphIntegrationError("Checkpoint must contain an id")
        self._put_row(thread_id, namespace, checkpoint_id, parent_id, self._encode(checkpoint), self._encode(dict(metadata)))
        return {**dict(config), "configurable": {**dict(config.get("configurable", {})), "checkpoint_id": checkpoint_id}}

    def _put_row(self, thread_id: str, namespace: str, checkpoint_id: str, parent_id: str | None, checkpoint: bytes, metadata: bytes) -> None:
        if self._orm:
            record = LangGraphCheckpointRecord.query().filter(thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint_id).first()
            values = {"parent_id": parent_id or "", "checkpoint_payload": checkpoint.decode(), "metadata_payload": metadata.decode(), "created_at": time.time_ns()}
            if record:
                for key, value in values.items(): setattr(record, key, value)
            else:
                record = LangGraphCheckpointRecord(thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint_id, **values)
            record.save()
            if self._redis is not None:
                self._cache_checkpoint(thread_id, namespace, checkpoint_id, parent_id, checkpoint, metadata)
            return
        if self._redis is not None:
            key = self._redis_checkpoint_key(thread_id, namespace, checkpoint_id)
            payload = json.dumps({"parent_id": parent_id, "checkpoint": checkpoint.decode(), "metadata": metadata.decode()})
            pipe = self._redis.pipeline(transaction=True)
            pipe.set(key, payload)
            pipe.zadd(self._redis_scope_key(thread_id, namespace), {checkpoint_id: time.time_ns()})
            pipe.execute()
            return
        with self._sync_lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id,parent_id,checkpoint,metadata) VALUES(?,?,?,?,?,?)", (thread_id, namespace, checkpoint_id, parent_id, checkpoint, metadata))

    async def aput_writes(self, config: Mapping[str, Any], writes: list[tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        thread_id, namespace, checkpoint_id = self._scope(config)
        if not checkpoint_id:
            raise LangGraphIntegrationError("Pending writes require checkpoint_id")
        async with self._async_lock:
            self._put_writes(thread_id, namespace, checkpoint_id, writes, task_id)

    def put_writes(self, config, writes, task_id, task_path=""):
        thread_id, namespace, checkpoint_id = self._scope(config)
        self._put_writes(thread_id, namespace, checkpoint_id, writes, task_id)

    def _put_writes(self, thread_id: str, namespace: str, checkpoint_id: str, writes: list[tuple[str, Any]], task_id: str) -> None:
        if self._orm:
            for idx, (channel, value) in enumerate(writes):
                record = LangGraphWriteRecord.query().filter(thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint_id, task_id=task_id, write_index=idx).first()
                payload = {"channel": channel, "value_payload": self._encode(value).decode()}
                if record:
                    for key, item in payload.items(): setattr(record, key, item)
                else:
                    record = LangGraphWriteRecord(thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint_id, task_id=task_id, write_index=idx, **payload)
                record.save()
                if self._redis is not None:
                    self._redis.hset(self._redis_write_key(thread_id, namespace, checkpoint_id), f"{task_id}:{idx}", json.dumps({"task_id": task_id, "channel": channel, "value": payload["value_payload"]}))
            return
        if self._redis is not None:
            key = self._redis_write_key(thread_id, namespace, checkpoint_id)
            pipe = self._redis.pipeline(transaction=True)
            for idx, (channel, value) in enumerate(writes):
                pipe.hset(key, f"{task_id}:{idx}", json.dumps({"task_id": task_id, "channel": channel, "value": self._encode(value).decode()}))
            pipe.execute()
            return
        with self._sync_lock, self._connect() as db:
            for idx, (channel, value) in enumerate(writes):
                db.execute("INSERT OR REPLACE INTO writes VALUES(?,?,?,?,?,?,?)", (thread_id, namespace, checkpoint_id, task_id, idx, channel, self._encode(value)))

    async def aget_tuple(self, config: Mapping[str, Any]) -> Any:
        thread_id, namespace, checkpoint_id = self._scope(config)
        async with self._async_lock:
            row = self._get_row(thread_id, namespace, checkpoint_id)
        if row is None:
            return None
        checkpoint, metadata, parent_id = row
        result_config = {**dict(config), "configurable": {**dict(config.get("configurable", {})), "thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": checkpoint["id"]}}
        parent_config = None if not parent_id else {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": parent_id}}
        return CheckpointTuple(result_config, checkpoint, self._decode(metadata), parent_config, self._pending_writes(thread_id, namespace, checkpoint["id"]))

    def get_tuple(self, config):
        thread_id, namespace, checkpoint_id = self._scope(config)
        row = self._get_row(thread_id, namespace, checkpoint_id)
        if row is None:
            return None
        checkpoint, metadata, parent_id = row
        result_config = {**dict(config), "configurable": {**dict(config.get("configurable", {})), "thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": checkpoint["id"]}}
        parent_config = None if not parent_id else {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": parent_id}}
        return CheckpointTuple(result_config, checkpoint, self._decode(metadata), parent_config, self._pending_writes(thread_id, namespace, checkpoint["id"]))

    def _get_row(self, thread_id: str, namespace: str, checkpoint_id: str | None):
        if self._orm:
            if self._redis is not None and checkpoint_id is not None:
                cached = self._redis.get(self._redis_checkpoint_key(thread_id, namespace, checkpoint_id))
                if cached:
                    record = json.loads(cached.decode() if isinstance(cached, bytes) else cached)
                    return self._decode(record["checkpoint"].encode()), record["metadata"].encode(), record.get("parent_id")
            query = LangGraphCheckpointRecord.query().filter(thread_id=thread_id, checkpoint_ns=namespace)
            records = query.filter(checkpoint_id=checkpoint_id).all() if checkpoint_id else query.all()
            record = max(records, key=lambda item: item.created_at or 0.0, default=None)
            if not record:
                return None
            if self._redis is not None:
                self._cache_checkpoint(thread_id, namespace, record.checkpoint_id, record.parent_id or None, record.checkpoint_payload.encode(), record.metadata_payload.encode())
            return self._decode(record.checkpoint_payload.encode()), record.metadata_payload.encode(), record.parent_id or None
        if self._redis is not None:
            if checkpoint_id is None:
                values = self._redis.zrevrange(self._redis_scope_key(thread_id, namespace), 0, 0)
                if not values:
                    return None
                checkpoint_id = values[0].decode() if isinstance(values[0], bytes) else values[0]
            raw = self._redis.get(self._redis_checkpoint_key(thread_id, namespace, checkpoint_id))
            if not raw:
                return None
            record = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            return self._decode(record["checkpoint"].encode()), record["metadata"].encode(), record.get("parent_id")
        with self._sync_lock, self._connect() as db:
            row = db.execute("SELECT checkpoint,parent_id,metadata FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=COALESCE(?,(SELECT checkpoint_id FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? ORDER BY rowid DESC LIMIT 1))", (thread_id, namespace, checkpoint_id, thread_id, namespace)).fetchone()
        if not row:
            return None
        return self._decode(row[0]), row[2], row[1]

    def _pending_writes(self, thread_id: str, namespace: str, checkpoint_id: str) -> list[tuple[str, str, Any]]:
        if self._orm:
            if self._redis is not None:
                cached = self._redis.hgetall(self._redis_write_key(thread_id, namespace, checkpoint_id))
                if cached:
                    rows = []
                    for raw in cached.values():
                        item = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                        rows.append((item["task_id"], item["channel"], self._decode(item["value"].encode())))
                    return sorted(rows, key=lambda item: (item[0], item[1]))
            records = LangGraphWriteRecord.query().filter(thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint_id).all()
            records.sort(key=lambda item: (item.task_id, item.write_index))
            return [(item.task_id, item.channel, self._decode(item.value_payload.encode())) for item in records]
        if self._redis is not None:
            values = self._redis.hgetall(self._redis_write_key(thread_id, namespace, checkpoint_id))
            rows = []
            for raw in values.values():
                record = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                rows.append((record["task_id"], record["channel"], self._decode(record["value"].encode())))
            return sorted(rows, key=lambda item: (item[0], item[1]))
        with self._sync_lock, self._connect() as db:
            rows = db.execute("SELECT task_id, channel, value FROM writes WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=? ORDER BY task_id, idx", (thread_id, namespace, checkpoint_id)).fetchall()
        return [(task_id, channel, self._decode(value)) for task_id, channel, value in rows]

    async def alist(self, config: Mapping[str, Any] | None = None, *, filter: Mapping[str, Any] | None = None, before: Mapping[str, Any] | None = None, limit: int | None = None):
        thread_id = namespace = None
        if config:
            thread_id, namespace, _ = self._scope(config)
        before_id = self._scope(before)[2] if before else None
        async with self._async_lock:
            rows = self._list_rows(thread_id, namespace, before_id, limit)
        for checkpoint, metadata, checkpoint_id, parent_id in rows:
            decoded_metadata = self._decode(metadata)
            if filter and any(decoded_metadata.get(key) != value for key, value in filter.items()):
                continue
            checkpoint_value = self._decode(checkpoint["data"])
            parent_config = None if not parent_id else {"configurable": {"thread_id": checkpoint["thread_id"], "checkpoint_ns": checkpoint["checkpoint_ns"], "checkpoint_id": parent_id}}
            yield CheckpointTuple({"configurable": {"thread_id": checkpoint["thread_id"], "checkpoint_ns": checkpoint["checkpoint_ns"], "checkpoint_id": checkpoint_id}}, checkpoint_value, decoded_metadata, parent_config, self._pending_writes(checkpoint["thread_id"], checkpoint["checkpoint_ns"], checkpoint_id))

    def list(self, config=None, *, filter=None, before=None, limit=None):
        thread_id = namespace = None
        if config:
            thread_id, namespace, _ = self._scope(config)
        before_id = self._scope(before)[2] if before else None
        for checkpoint, metadata, checkpoint_id, parent_id in self._list_rows(thread_id, namespace, before_id, limit):
            decoded_metadata = self._decode(metadata)
            if filter and any(decoded_metadata.get(key) != value for key, value in filter.items()):
                continue
            checkpoint_value = self._decode(checkpoint["data"])
            parent_config = None if not parent_id else {"configurable": {"thread_id": checkpoint["thread_id"], "checkpoint_ns": checkpoint["checkpoint_ns"], "checkpoint_id": parent_id}}
            yield CheckpointTuple({"configurable": {"thread_id": checkpoint["thread_id"], "checkpoint_ns": checkpoint["checkpoint_ns"], "checkpoint_id": checkpoint_id}}, checkpoint_value, decoded_metadata, parent_config, self._pending_writes(checkpoint["thread_id"], checkpoint["checkpoint_ns"], checkpoint_id))

    def _list_rows(self, thread_id, namespace, before_id=None, limit=None):
        if self._orm:
            if thread_id is None:
                records = LangGraphCheckpointRecord.query().all()
            else:
                records = LangGraphCheckpointRecord.query().filter(thread_id=thread_id, checkpoint_ns=namespace).all()
            records.sort(key=lambda item: item.created_at or 0.0, reverse=True)
            if before_id:
                before = next((item for item in records if item.checkpoint_id == before_id), None)
                if before:
                    records = [item for item in records if (item.created_at or 0.0) < (before.created_at or 0.0)]
            if limit is not None:
                records = records[:max(0, int(limit))]
            return [({"thread_id": item.thread_id, "checkpoint_ns": item.checkpoint_ns, "data": item.checkpoint_payload.encode()}, item.metadata_payload.encode(), item.checkpoint_id, item.parent_id or None) for item in records]
        if self._redis is not None:
            if thread_id is None:
                raise LangGraphIntegrationError("Redis checkpointer list requires a scoped thread_id")
            ids = self._redis.zrevrange(self._redis_scope_key(thread_id, namespace), 0, -1)
            result = []
            before_score = None
            if before_id:
                before_score = self._redis.zscore(self._redis_scope_key(thread_id, namespace), before_id)
            for raw_id in ids:
                checkpoint_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
                score = self._redis.zscore(self._redis_scope_key(thread_id, namespace), checkpoint_id)
                if before_score is not None and (score is None or score >= before_score):
                    continue
                raw = self._redis.get(self._redis_checkpoint_key(thread_id, namespace, checkpoint_id))
                if not raw:
                    continue
                record = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                result.append(({"thread_id": thread_id, "checkpoint_ns": namespace, "data": record["checkpoint"].encode()}, record["metadata"].encode(), checkpoint_id, record.get("parent_id")))
                if limit is not None and len(result) >= max(0, int(limit)):
                    break
            return result
        with self._sync_lock, self._connect() as db:
            query = "SELECT thread_id,checkpoint_ns,checkpoint_id,checkpoint,metadata FROM checkpoints"
            args = []
            if thread_id is not None:
                query += " WHERE thread_id=? AND checkpoint_ns=?"
                args.extend([thread_id, namespace])
            if before_id is not None:
                query += " AND " if thread_id is not None else " WHERE "
                query += "rowid < (SELECT rowid FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?)"
                args.extend([thread_id, namespace, before_id])
            query += " ORDER BY rowid DESC"
            if limit is not None:
                query += " LIMIT ?"
                args.append(max(0, int(limit)))
            return [( {"thread_id": r[0], "checkpoint_ns": r[1], "data": r[3]}, r[4], r[2], r[5]) for r in db.execute(query.replace("checkpoint,metadata", "checkpoint,metadata,parent_id"), args).fetchall()]


def thinkdome_tool(
    func: Callable[..., Awaitable[Any] | Any],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Any:
    """Wrap a function as a LangGraph/LangChain tool when installed.

    Without LangChain, the original callable is returned so applications can
    still use the adapter in custom graph nodes or MCP bridges.
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        return func
    return StructuredTool.from_function(
        coroutine=func if inspect.iscoroutinefunction(func) else None,
        func=func if not inspect.iscoroutinefunction(func) else None,
        name=name or func.__name__,
        description=description or (inspect.getdoc(func) or "ThinkDome tool"),
    )
