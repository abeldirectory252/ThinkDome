"""Unit tests for the pre-warmed sandbox pool manager."""

import pytest
import asyncio
import time
from thinkdome.sandbox.pool.manager import PoolManager, ContainerState
from thinkdome.core.config import Settings


@pytest.fixture
def mock_settings():
    settings = Settings()
    settings.POOL_MIN_WARM = 2
    settings.POOL_MAX_SIZE = 5
    settings.POOL_EVICTION_GRACE_SEC = 2
    settings.POOL_DEMAND_WINDOW_SEC = 5
    settings.POOL_ENABLED = True
    return settings


@pytest.mark.asyncio
async def test_pool_manager_initialization_and_prewarm(mock_settings):
    # Initialize in dry-run mode (no docker client passed)
    pool = PoolManager(mock_settings, docker_client=None)
    await pool.start()
    
    status = pool.get_status()
    assert status["total_containers"] == 2
    assert status["states"].get("warm") == 2
    assert status["demand_ema"] == 0.0
    
    await pool.stop()


@pytest.mark.asyncio
async def test_pool_manager_acquire_and_release(mock_settings):
    pool = PoolManager(mock_settings, docker_client=None)
    await pool.start()

    # 1. Acquire warm container
    pooled = await pool.acquire(role="LLM")
    assert pooled is not None
    assert pooled.state == ContainerState.ACQUIRED
    assert pooled.use_count == 1

    status = pool.get_status()
    assert status["states"].get("acquired") == 1
    assert status["states"].get("warm") == 1
    assert status["cache_hits"] == 1

    # 2. Release back to pool
    await pool.release(pooled.pool_id, reset=False)
    status = pool.get_status()
    assert status["states"].get("warm") == 2
    assert status["states"].get("acquired") is None

    await pool.stop()


@pytest.mark.asyncio
async def test_pool_manager_cold_start_fallback(mock_settings):
    pool = PoolManager(mock_settings, docker_client=None)
    await pool.start()

    # Exhaust the pool (acquire 2)
    c1 = await pool.acquire(role="LLM")
    c2 = await pool.acquire(role="LLM")
    assert c1 is not None
    assert c2 is not None

    # Try to acquire 3rd (triggers cold start mock creation)
    c3 = await pool.acquire(role="LLM")
    assert c3 is not None
    assert c3.state == ContainerState.ACQUIRED

    status = pool.get_status()
    assert status["cold_starts"] == 1
    assert status["states"].get("acquired") == 3

    await pool.stop()


@pytest.mark.asyncio
async def test_pool_manager_lazy_eviction_and_demand_scaling(mock_settings):
    pool = PoolManager(mock_settings, docker_client=None)
    await pool.start()

    # Evict containers manually by calling scale down logic helper
    now = time.monotonic()
    # Mark one of the warm containers as cooling
    for container in pool._containers.values():
        container.state = ContainerState.COOLING
        container.cooling_deadline = now + 1
        break

    status = pool.get_status()
    assert status["states"].get("cooling") == 1

    # Wait for grace period and run one maintenance cycle
    await asyncio.sleep(1.5)
    await pool._run_maintenance()

    # Maintenance should have evict-destroyed the cooling container
    status = pool.get_status()
    assert status["states"].get("cooling") is None

    await pool.stop()
