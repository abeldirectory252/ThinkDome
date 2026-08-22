from thinkdome.control_plane.cache import RedisNodeHeartbeatCache
from thinkdome.control_plane.contracts import NodeCapacity, NodeHeartbeat


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def scan_iter(self, match):
        return iter(self.values)

    def get(self, key):
        return self.values[key]


def test_redis_node_cache_round_trip():
    cache = RedisNodeHeartbeatCache(FakeRedis())
    heartbeat = NodeHeartbeat(
        node_id="node-a",
        orchestrator_version="1",
        capacity=NodeCapacity(cpu_millis=1000, memory_bytes=1024, pids=10, sandboxes=0),
    )
    cache.put(heartbeat)
    assert cache.get_ready()[0].node_id == "node-a"
