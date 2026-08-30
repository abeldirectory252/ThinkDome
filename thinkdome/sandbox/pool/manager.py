"""Pre-warmed sandbox pool manager for ultra-low cold-start latency.

Maintains a pool of idle, pre-booted Docker containers that can be
acquired in <60ms instead of paying the ~300-800ms cold-start penalty.

Features:
  - Pre-warm pool with configurable min/max sizes
  - Demand-based scaling via exponential moving average
  - Lazy eviction with grace period to handle bursty traffic
  - Snapshot/restore: reset container workspace instead of destroy+recreate
  - Even placement across available capacity
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Deque

from thinkdome.sandbox.executors.docker.container_policy import DockerContainerPolicy

logger = logging.getLogger(__name__)


class ContainerState(str, Enum):
    WARM = "warm"           # Idle, ready for use
    ACQUIRED = "acquired"   # In-use by a request
    COOLING = "cooling"     # Marked for lazy eviction, still usable
    RESETTING = "resetting" # Cleanup in progress; never acquire or release
    DEAD = "dead"           # Removed or failed


@dataclass
class PooledContainer:
    """Represents a container managed by the pool."""
    container_id: str
    pool_id: str                              # Internal tracking ID
    image: str
    state: ContainerState = ContainerState.WARM
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    cooling_deadline: Optional[float] = None  # When to actually destroy (lazy eviction)
    use_count: int = 0                        # How many times this container has been reused
    lease_token: str = ""                    # Per-acquisition capability token


class PoolManager:
    """Manages a pool of pre-warmed Docker containers for fast acquisition.

    Usage:
        pool = PoolManager(settings, docker_client, image="thinkdome-executor:latest")
        await pool.start()

        # Acquire a warm container (<60ms target)
        container = await pool.acquire(role="LLM")
        # ... use container ...
        await pool.release(container.pool_id)

        await pool.stop()
    """

    def __init__(
        self,
        settings,
        docker_client=None,
        image: str = "thinkdome-executor:latest",
    ) -> None:
        self.settings = settings
        self.docker_client = docker_client
        self.image = image

        # Pool configuration
        self._min_warm = settings.POOL_MIN_WARM
        self._max_size = settings.POOL_MAX_SIZE
        self._eviction_grace_sec = settings.POOL_EVICTION_GRACE_SEC
        self._demand_window_sec = settings.POOL_DEMAND_WINDOW_SEC

        # Container registry: pool_id -> PooledContainer
        self._containers: Dict[str, PooledContainer] = {}

        # Request timestamps for demand estimation (rolling window)
        self._request_times: Deque[float] = deque()

        # Exponential moving average of requests/sec
        self._demand_ema: float = 0.0
        self._ema_alpha: float = 0.3  # Smoothing factor

        # Background maintenance task
        self._maintenance_task: Optional[asyncio.Task] = None
        self._running = False
        # Serializes cold container creation.  Without a gate, concurrent
        # misses can all observe the same pool size and overshoot the hard
        # POOL_MAX_SIZE resource bound while awaiting Docker.
        self._create_lock = asyncio.Lock()

        # Metrics
        self._total_acquisitions: int = 0
        self._cache_hits: int = 0
        self._cold_starts: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the pool manager and pre-warm containers."""
        if not self.docker_client:
            logger.warning("Pool manager started without Docker client — operating in dry-run/mock mode")

        self._running = True
        logger.info(
            f"🏊 Pool manager starting: min_warm={self._min_warm}, "
            f"max_size={self._max_size}, eviction_grace={self._eviction_grace_sec}s"
        )

        # Pre-warm initial containers
        warm_count = 0
        for _ in range(self._min_warm):
            try:
                async with self._create_lock:
                    if len(self._containers) >= self._max_size:
                        break
                    await self._create_warm_container()
                warm_count += 1
            except Exception as e:
                logger.error(f"Failed to pre-warm container: {e}")

        logger.info(f"🔥 Pre-warmed {warm_count}/{self._min_warm} containers")

        # Start background maintenance loop
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        """Stop the pool manager and destroy all containers."""
        self._running = False

        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        # Destroy all pooled containers
        destroyed = 0
        for pool_id in list(self._containers.keys()):
            try:
                await self._destroy_container(pool_id)
                destroyed += 1
            except Exception as e:
                logger.error(f"Error destroying pooled container {pool_id}: {e}")

        logger.info(
            f"🏊 Pool manager stopped. Destroyed {destroyed} containers. "
            f"Stats: acquisitions={self._total_acquisitions}, "
            f"hits={self._cache_hits}, cold_starts={self._cold_starts}"
        )

    # ── Acquire / Release ──────────────────────────────────────────────────────

    async def acquire(self, role: str = "LLM") -> Optional[PooledContainer]:
        """Acquire a warm container from the pool.

        Returns a PooledContainer if one is available, None otherwise.
        Target latency: <60ms for a pool hit.
        """
        self._total_acquisitions += 1
        now = time.monotonic()
        self._request_times.append(now)

        # Find a warm container
        for pool_id, container in self._containers.items():
            if container.state in (ContainerState.WARM, ContainerState.COOLING):
                container.state = ContainerState.ACQUIRED
                container.lease_token = uuid.uuid4().hex
                container.last_used_at = now
                container.use_count += 1
                container.cooling_deadline = None  # Cancel any pending eviction
                self._cache_hits += 1

                logger.debug(
                    f"⚡ Pool HIT: acquired {pool_id} "
                    f"(use_count={container.use_count}, latency<1ms)"
                )
                return container

        # No warm container available — cold start
        self._cold_starts += 1
        logger.info(f"❄️ Pool MISS: no warm containers available, cold-starting for role={role}")

        async with self._create_lock:
            # Another waiter may have created a container while this request
            # was queued. Reuse it before allocating another Docker resource.
            for container in self._containers.values():
                if container.state in (ContainerState.WARM, ContainerState.COOLING):
                    container.state = ContainerState.ACQUIRED
                    container.lease_token = uuid.uuid4().hex
                    container.last_used_at = time.monotonic()
                    container.use_count += 1
                    container.cooling_deadline = None
                    self._cache_hits += 1
                    return container
            if len(self._containers) >= self._max_size:
                logger.warning("Pool at hard capacity (%s); refusing cold start", self._max_size)
                return None
            try:
                container = await self._create_warm_container()
                container.state = ContainerState.ACQUIRED
                container.use_count = 1
                container.lease_token = uuid.uuid4().hex
                return container
            except Exception as e:
                logger.error(f"Failed to create container on cold start: {e}")
                return None

    async def release(
        self,
        pool_id: str,
        reset: bool = True,
        lease_token: str | None = None,
    ) -> None:
        """Release a container back to the pool after use.

        If reset=True, the container's /workspace is wiped before returning
        to the warm pool (snapshot/restore pattern).
        """
        container = self._containers.get(pool_id)
        if not container:
            logger.warning(f"Attempted to release unknown container {pool_id}")
            return

        if lease_token is not None and lease_token != container.lease_token:
            logger.warning("Rejected stale lease release for container %s", pool_id)
            return

        if container.state != ContainerState.ACQUIRED:
            # Release can be retried after cancellation/timeout. Never reset
            # or requeue a container that another request may already own;
            # doing so permits concurrent executions to share workspace state.
            logger.warning(f"Container {pool_id} released but state is {container.state}")
            return

        if not reset:
            # A failed/timed-out execution may have unknown process and
            # filesystem state. It must never be returned as a warm container.
            await self._destroy_container(pool_id)
            return

        # Reserve the container before awaiting Docker cleanup. A duplicate
        # release must not reset or requeue the same container concurrently.
        container.state = ContainerState.RESETTING

        # Check pool capacity
        warm_count = sum(1 for c in self._containers.values() if c.state == ContainerState.WARM)
        if warm_count >= self._max_size:
            # Pool is full — destroy instead of returning
            logger.debug(f"Pool full ({warm_count}/{self._max_size}), destroying {pool_id}")
            await self._destroy_container(pool_id)
            return

        # Reset workspace (snapshot/restore)
        if reset and self.docker_client:
            try:
                await self._reset_container(container)
            except Exception as e:
                logger.warning(f"Failed to reset container {pool_id}, destroying: {e}")
                await self._destroy_container(pool_id)
                return

        container.state = ContainerState.WARM
        container.last_used_at = time.monotonic()
        logger.debug(f"♻️ Container {pool_id} returned to warm pool (use_count={container.use_count})")

    async def pause_container(self, pool_id: str) -> None:
        """Pause a container in the pool."""
        container = self._containers.get(pool_id)
        if not container:
            return
        if self.docker_client and container.container_id and not container.container_id.startswith("dry_"):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.docker_client.containers.get(container.container_id).pause())
        logger.debug(f"⏸️ Pooled container {pool_id} paused")

    async def resume_container(self, pool_id: str) -> None:
        """Resume a paused container in the pool."""
        container = self._containers.get(pool_id)
        if not container:
            return
        if self.docker_client and container.container_id and not container.container_id.startswith("dry_"):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.docker_client.containers.get(container.container_id).unpause())
        logger.debug(f"▶️ Pooled container {pool_id} resumed")

    # ── Internal Container Operations ──────────────────────────────────────────

    async def _create_warm_container(self) -> PooledContainer:
        """Create a new pre-warmed container and add it to the pool."""
        pool_id = f"pool_{uuid.uuid4().hex[:12]}"

        if self.docker_client:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(None, self._create_container_sync)
            container_id = container.id
        else:
            # Dry-run mode (no Docker)
            container_id = f"dry_{uuid.uuid4().hex[:12]}"

        pooled = PooledContainer(
            container_id=container_id,
            pool_id=pool_id,
            image=self.image,
        )
        self._containers[pool_id] = pooled

        logger.debug(f"🆕 Created warm container {pool_id} (id={container_id[:12]})")
        return pooled

    def _create_container_sync(self):
        """Synchronous Docker container creation with security hardening."""
        import os

        self.settings.validate_production_runtime()
        from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup
        validate_secure_runtime_on_startup(self.settings, docker_client=self.docker_client)
        # Load seccomp profile
        security_opt = ["no-new-privileges:true"]
        from thinkdome.core.config import get_workspace_root
        seccomp_path = str(get_workspace_root() / "security" / "seccomp.json")

        if os.path.exists(seccomp_path):
            with open(seccomp_path) as f:
                security_opt.append(f"seccomp={f.read()}")

        # GPU support
        device_requests = []
        if getattr(self.settings, 'GPU_ENABLED', False):
            import docker as _docker
            gpu_count = getattr(self.settings, 'GPU_MAX_PER_SANDBOX', 1)
            device_requests.append(
                _docker.types.DeviceRequest(count=gpu_count, capabilities=[["gpu"]])
            )

        config = DockerContainerPolicy.pool_config(self.settings, self.image, security_opt, device_requests)
        # A pooled container is acquired through exec_create/exec_start, so it
        # must be running before it is published as WARM.  Docker's
        # containers.create() API only creates the container and leaves it in
        # the Created state; publishing that object without starting it makes
        # every pool hit fail at exec time.
        container = self.docker_client.containers.create(**config)
        try:
            container.start()
        except Exception:
            # Do not leave an unusable container behind when startup fails.
            try:
                container.remove(force=True)
            except Exception:
                logger.exception("Failed to remove pooled container after startup failure")
            raise
        return container

    async def _reset_container(self, container: PooledContainer) -> None:
        """Reset a container's workspace to clean state (snapshot/restore pattern)."""
        if not self.docker_client:
            return

        loop = asyncio.get_event_loop()

        def _reset_sync():
            try:
                docker_container = self.docker_client.containers.get(container.container_id)
                # Warm containers are shared across requests. Restart through
                # Docker before reuse so helper processes started by the
                # untrusted program are terminated even when they changed UID
                # or are not signalable by the sandbox user. Deleting files
                # alone does not stop background descendants.
                docker_container.restart(timeout=2)
                # Clear /workspace by removing and recreating tmpfs content
                workspace = docker_container.exec_run(
                    ["sh", "-c", "rm -rf /workspace/* /workspace/.[!.]* 2>/dev/null || true"],
                    user="0:0",
                )
                # Clear /tmp
                tmp = docker_container.exec_run(
                    ["sh", "-c", "rm -rf /tmp/* /tmp/.[!.]* 2>/dev/null || true"],
                    user="0:0",
                )
                if getattr(workspace, "exit_code", 0) not in (0, None) or getattr(tmp, "exit_code", 0) not in (0, None):
                    raise RuntimeError("sandbox workspace reset failed")
            except Exception as e:
                raise RuntimeError(f"Container reset failed: {e}")

        await loop.run_in_executor(None, _reset_sync)

    async def _destroy_container(self, pool_id: str) -> None:
        """Remove a container from the pool and destroy it."""
        container = self._containers.pop(pool_id, None)
        if not container:
            return

        container.state = ContainerState.DEAD

        if self.docker_client:
            loop = asyncio.get_event_loop()

            def _remove_sync():
                try:
                    docker_container = self.docker_client.containers.get(container.container_id)
                    docker_container.remove(force=True)
                except Exception:
                    pass

            await loop.run_in_executor(None, _remove_sync)

        logger.debug(f"🗑️ Destroyed container {pool_id}")

    # ── Background Maintenance ─────────────────────────────────────────────────

    async def _maintenance_loop(self) -> None:
        """Background loop: demand estimation, scaling, lazy eviction."""
        while self._running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                await self._run_maintenance()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Pool maintenance error: {e}")

    async def _run_maintenance(self) -> None:
        """Single maintenance cycle."""
        now = time.monotonic()

        # 1. Update demand estimation
        self._update_demand(now)

        # 2. Idle sandbox reaping — kill containers unused beyond IDLE_TIMEOUT_SEC
        idle_timeout = getattr(self.settings, 'IDLE_TIMEOUT_SEC', 600)
        for pool_id in list(self._containers.keys()):
            container = self._containers.get(pool_id)
            if not container:
                continue
            idle_sec = now - container.last_used_at
            if (
                container.state == ContainerState.WARM
                and idle_sec > idle_timeout
            ):
                logger.info(f"💤 Idle reap: {pool_id} idle for {idle_sec:.0f}s > {idle_timeout}s")
                await self._destroy_container(pool_id)
                continue

            # 3. Lazy eviction — destroy containers past their grace period
            if (
                container.state == ContainerState.COOLING
                and container.cooling_deadline
                and now >= container.cooling_deadline
            ):
                logger.debug(f"⏰ Lazy eviction: destroying {pool_id}")
                await self._destroy_container(pool_id)

        # 4. Scale pool based on demand
        warm_count = sum(
            1 for c in self._containers.values()
            if c.state in (ContainerState.WARM, ContainerState.COOLING)
        )

        # Target warm count: max(min_warm, demand_ema * 1.5)
        target = max(self._min_warm, int(self._demand_ema * 1.5))
        target = min(target, self._max_size)

        if warm_count < target:
            # Scale up
            to_create = min(target - warm_count, 3)
            for _ in range(to_create):
                try:
                    async with self._create_lock:
                        if len(self._containers) >= self._max_size:
                            break
                        await self._create_warm_container()
                except Exception as e:
                    logger.error(f"Scale-up failed: {e}")
                    break

        elif warm_count > target + 2:
            # Scale down — mark excess containers as cooling
            excess = warm_count - target
            for pool_id, container in self._containers.items():
                if excess <= 0:
                    break
                if container.state == ContainerState.WARM:
                    container.state = ContainerState.COOLING
                    container.cooling_deadline = now + self._eviction_grace_sec
                    excess -= 1
                    logger.debug(
                        f"🧊 Marked {pool_id} for lazy eviction "
                        f"(deadline={self._eviction_grace_sec}s)"
                    )

    def _update_demand(self, now: float) -> None:
        """Update the rolling demand estimation (requests/sec EMA)."""
        # Trim old request timestamps outside the window
        cutoff = now - self._demand_window_sec
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

        # Current request rate
        if self._demand_window_sec > 0:
            current_rate = len(self._request_times) / self._demand_window_sec
        else:
            current_rate = 0.0

        # Update EMA
        self._demand_ema = (
            self._ema_alpha * current_rate
            + (1 - self._ema_alpha) * self._demand_ema
        )

    # ── Metrics / Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return pool status metrics."""
        states = {}
        for c in self._containers.values():
            states[c.state.value] = states.get(c.state.value, 0) + 1

        return {
            "total_containers": len(self._containers),
            "states": states,
            "demand_ema": round(self._demand_ema, 3),
            "total_acquisitions": self._total_acquisitions,
            "cache_hits": self._cache_hits,
            "cold_starts": self._cold_starts,
            "hit_rate": (
                round(self._cache_hits / self._total_acquisitions, 3)
                if self._total_acquisitions > 0
                else 0.0
            ),
            "config": {
                "min_warm": self._min_warm,
                "max_size": self._max_size,
                "eviction_grace_sec": self._eviction_grace_sec,
            },
        }
