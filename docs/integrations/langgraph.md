# LangGraph Integration

ThinkDome can be used as the secure execution layer for LangGraph without
making LangGraph a core dependency.

Install the optional integration dependencies:

```bash
pip install 'thinkdome[langgraph]'
```

## Sandbox node

```python
from thinkdome import Sandbox
from thinkdome.integrations.langgraph import ThinkDomeSandboxNode

sandbox = Sandbox(
    backend="docker",
    network_allowed=False,
    memory_limit=256,
)

node = ThinkDomeSandboxNode(
    sandbox=sandbox,
    code_builder=lambda state: f"print({state['value']} * 2)",
)

# Add `node` to a LangGraph StateGraph as an async node.
result_state = await node({"value": 21})
await node.aclose()
```

The node serializes calls against its sandbox. Do not share one node between
independent graph runs; create one node per graph-run ownership boundary.

## Checkpoints

```python
from thinkdome.integrations.langgraph import ThinkDomeCheckpointStore

checkpoints = ThinkDomeCheckpointStore(node)
await checkpoints.put("before_tool", {"step": 1})
await checkpoints.restore("before_tool")
await checkpoints.delete("before_tool")
```

Checkpoint metadata is recovered from persisted ThinkDome snapshot metadata
after process restart. Deletion removes the underlying snapshot files.

### Native LangGraph checkpointer

For a LangGraph `StateGraph`, use the native adapter when the graph runtime
expects `BaseCheckpointSaver` methods (`put`, `put_writes`, `get_tuple`, and
`list`, including async variants):

```python
from thinkdome.integrations.langgraph import ThinkDomeLangGraphCheckpointer

checkpointer = ThinkDomeLangGraphCheckpointer(
    path="/var/lib/thinkdome/langgraph/checkpoints.sqlite3",
)
compiled = graph.compile(checkpointer=checkpointer)
```

The adapter stores serialized checkpoints and pending writes in SQLite with
WAL mode and scoped `(thread_id, checkpoint_ns)` keys. It is safe for
concurrent calls within one process. Put the database on durable, access-
controlled storage; a local SQLite file is not a multi-worker/shared-database
solution. For multiple workers, use a supported shared LangGraph checkpointer
or a database service with an appropriate locking/backup strategy.

For production workers, use Redis as the shared persistence backend:

```python
checkpointer = ThinkDomeLangGraphCheckpointer(
    redis_url="redis://redis.internal:6379/3",
    redis_prefix="thinkdome:langgraph:prod",
)
```

Redis keys are namespace-scoped and checkpoint payloads include pending writes
and parent relationships. Configure Redis persistence, authentication, TLS,
network policy, and eviction protection; do not use an eviction-enabled cache
as the sole checkpoint store.

## Tools

```python
from thinkdome.integrations.langgraph import thinkdome_tool

async def inspect_workspace(path: str) -> str:
    """Inspect an authorized path in the current graph sandbox."""
    return path

tool = thinkdome_tool(inspect_workspace)
```

When `langchain-core` is installed, this returns a `StructuredTool`; otherwise
the original callable is returned for custom graph adapters.

## Production requirements

- Use `backend="docker"` or `backend="microvm"`; never rely on automatic
  subprocess fallback for untrusted graph nodes.
- Keep `network_allowed=False` unless the egress proxy and allowlist have been
  verified on the same Docker daemon used by the graph workers.
- Close every node in a `finally` block.
- Use distinct sandbox/node instances for concurrent graph branches.
- Bound graph retries and delete obsolete checkpoints to avoid storage growth.
- Treat checkpoint metadata as execution state, not as an authorization token;
  ThinkDome still validates sandbox ownership and lifecycle state.
