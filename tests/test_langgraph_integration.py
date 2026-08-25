"""Contract tests for the optional LangGraph integration."""

from pathlib import Path
import asyncio
import tempfile

from thinkdome.integrations.langgraph import ThinkDomeLangGraphCheckpointer


def test_langgraph_integration_is_optional_and_stateful():
    source = Path("thinkdome/integrations/langgraph.py").read_text()
    assert "class ThinkDomeSandboxNode" in source
    assert "class ThinkDomeCheckpointStore" in source
    assert "async with self._lock" in source
    assert "from langchain_core.tools import StructuredTool" in source
    assert "except ImportError" in source
    assert "delete_snapshot" in source
    assert "class ThinkDomeLangGraphCheckpointer(BaseCheckpointSaver)" in source
    assert "async def aput" in source
    assert "async def aput_writes" in source
    assert "async def aget_tuple" in source
    assert "async def alist" in source
    assert "tenant_id" in source
    assert "thread_id" in source
    assert "_scoped_tag" in source
    assert "self._lock = asyncio.Lock()" in source
    assert "_validate_checkpoint_id" in source
    assert "def _hydrate" in source
    assert "list_snapshots" in source
    assert "await self.sandbox.__aexit__(None, None, None)" in source
    assert "self._closed = False" in source
    assert "ThinkDome sandbox node is closed" in source
    assert "timeout_seconds" in source
    assert "asyncio.wait_for" in source
    assert "previous = self._metadata.get(checkpoint_id)" in source
    assert "delete_snapshot" in source


def test_langgraph_extra_does_not_pollute_core_dependencies():
    pyproject = Path("pyproject.toml").read_text()
    assert "[project.optional-dependencies]" in pyproject
    assert "langgraph = [" in pyproject
    core = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "langgraph" not in core


def test_native_checkpointer_round_trip_and_pending_writes():
    with tempfile.TemporaryDirectory() as directory:
        store = ThinkDomeLangGraphCheckpointer(f"{directory}/checkpoints.sqlite3")
        config = {"configurable": {"thread_id": "tenant-a/thread-a", "checkpoint_ns": "graph"}}
        saved = store.put(config, {"id": "cp-1", "channel_values": {"answer": 42}}, {"step": 1}, {})
        assert saved["configurable"]["checkpoint_id"] == "cp-1"
        pending_config = {"configurable": {**saved["configurable"]}}
        store.put_writes(pending_config, [("answer", "pending")], "task-1")
        item = store.get_tuple(pending_config)
        assert item is not None
        assert item.checkpoint["channel_values"]["answer"] == 42
        assert item.metadata["step"] == 1
        assert item.pending_writes == [("task-1", "answer", "pending")]
        assert list(store.list(config))[0].config["configurable"]["checkpoint_id"] == "cp-1"


def test_native_checkpointer_async_round_trip():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            store = ThinkDomeLangGraphCheckpointer(f"{directory}/checkpoints.sqlite3")
            config = {"configurable": {"thread_id": "t", "checkpoint_ns": ""}}
            result = await store.aput(config, {"id": "cp-async"}, {"source": "test"}, {})
            item = await store.aget_tuple(result)
            assert item is not None
            assert item.checkpoint["id"] == "cp-async"
            assert [x async for x in store.alist(config)]

    asyncio.run(run())


def test_native_checkpointer_runs_compiled_langgraph():
    """Exercise the real LangGraph BaseCheckpointSaver contract when installed."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return
    from typing import TypedDict

    class State(TypedDict):
        value: int

    graph = StateGraph(State)
    graph.add_node("increment", lambda state: {"value": state["value"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    with tempfile.TemporaryDirectory() as directory:
        checkpointer = ThinkDomeLangGraphCheckpointer(f"{directory}/graph.sqlite3")
        app = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "integration-test"}}
        assert app.invoke({"value": 1}, config) == {"value": 2}
        tuple_value = checkpointer.get_tuple(config)
        assert tuple_value is not None
        assert tuple_value.checkpoint["channel_values"]["value"] == 2


def test_native_checkpointer_redis_backend_round_trip():
    class Pipeline:
        def __init__(self, owner):
            self.owner = owner
            self.operations = []
        def set(self, key, value): self.operations.append(("set", key, value)); return self
        def zadd(self, key, values): self.operations.append(("zadd", key, values)); return self
        def hset(self, key, field, value): self.operations.append(("hset", key, field, value)); return self
        def execute(self):
            for operation in self.operations:
                if operation[0] == "set": self.owner.values[operation[1]] = operation[2]
                elif operation[0] == "zadd":
                    self.owner.sorted.setdefault(operation[1], {}).update({k: v for k, v in operation[2].items()})
                else: self.owner.hashes.setdefault(operation[1], {})[operation[2]] = operation[3]

    class FakeRedis:
        def __init__(self): self.values, self.sorted, self.hashes = {}, {}, {}
        def pipeline(self, transaction=True): return Pipeline(self)
        def get(self, key): return self.values.get(key)
        def hgetall(self, key): return self.hashes.get(key, {})
        def zrevrange(self, key, start, end):
            items = sorted(self.sorted.get(key, {}).items(), key=lambda item: item[1], reverse=True)
            return [item[0] for item in items][start:] if end == -1 else [item[0] for item in items][start:end + 1]
        def zscore(self, key, member): return self.sorted.get(key, {}).get(member)

    store = ThinkDomeLangGraphCheckpointer(redis_client=FakeRedis())
    config = {"configurable": {"thread_id": "redis-thread"}}
    saved = store.put(config, {"id": "redis-cp"}, {"source": "test"}, {})
    assert store.get_tuple(saved).checkpoint["id"] == "redis-cp"
    assert list(store.list(config))[0].metadata["source"] == "test"
