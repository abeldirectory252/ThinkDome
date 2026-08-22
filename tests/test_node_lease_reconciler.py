import asyncio

import pytest

from thinkdome.control_plane.registry import NodeLeaseReconciler


@pytest.mark.asyncio
async def test_lease_reconciler_starts_and_stops_cleanly():
    class Registry:
        def __init__(self):
            self.calls = 0

        def reconcile_expired(self):
            self.calls += 1

    registry = Registry()
    reconciler = NodeLeaseReconciler(registry, interval_seconds=0.01)
    await reconciler.start()
    await asyncio.sleep(0.03)
    await reconciler.stop()
    assert registry.calls >= 1
