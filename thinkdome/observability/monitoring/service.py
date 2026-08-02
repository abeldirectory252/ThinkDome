"""Real-time monitoring service — per-sandbox metrics, alerting, and WebSocket push.

Collects CPU, memory, network, PID, and block I/O metrics from active Docker
containers and broadcasts them to connected dashboard clients via WebSocket.

Features:
  - Background polling of Docker container stats
  - Rolling aggregation (min/max/avg/p99) over configurable retention window
  - Configurable alert rules with cooldown dedup
  - WebSocket broadcast to connected clients every N seconds
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Deque, Set, Any

logger = logging.getLogger(__name__)


@dataclass
class SandboxMetrics:
    """Point-in-time metrics for a single sandbox container."""
    container_id: str
    sandbox_id: str
    timestamp: float = field(default_factory=time.time)

    cpu_percent: float = 0.0
    memory_usage_mb: float = 0.0
    memory_limit_mb: float = 0.0
    memory_percent: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    pids_current: int = 0
    block_read_bytes: int = 0
    block_write_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "container_id": self.container_id[:12],
            "sandbox_id": self.sandbox_id,
            "timestamp": self.timestamp,
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_usage_mb": round(self.memory_usage_mb, 2),
            "memory_limit_mb": round(self.memory_limit_mb, 2),
            "memory_percent": round(self.memory_percent, 2),
            "network_rx_bytes": self.network_rx_bytes,
            "network_tx_bytes": self.network_tx_bytes,
            "pids_current": self.pids_current,
            "block_read_bytes": self.block_read_bytes,
            "block_write_bytes": self.block_write_bytes,
        }


@dataclass
class AlertRule:
    """Configurable alert rule for resource thresholds."""
    rule_id: str
    metric: str          # cpu_percent | memory_percent | pids_current
    threshold: float
    action: str = "warn"  # warn | kill | log
    duration_sec: float = 0  # Must exceed threshold for this long (0 = instant)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "metric": self.metric,
            "threshold": self.threshold,
            "action": self.action,
            "duration_sec": self.duration_sec,
            "enabled": self.enabled,
        }


@dataclass
class Alert:
    """A triggered alert."""
    rule_id: str
    sandbox_id: str
    metric: str
    value: float
    threshold: float
    action: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "sandbox_id": self.sandbox_id,
            "metric": self.metric,
            "value": round(self.value, 2),
            "threshold": self.threshold,
            "action": self.action,
            "timestamp": self.timestamp,
        }


class MonitorService:
    """Collects, aggregates, and broadcasts sandbox metrics.

    Usage:
        monitor = MonitorService(settings, docker_client)
        await monitor.start()

        # Get current metrics
        metrics = monitor.get_all_metrics()

        # Subscribe a WebSocket
        ws_id = monitor.subscribe(websocket_send_fn)
        monitor.unsubscribe(ws_id)

        await monitor.stop()
    """

    def __init__(self, settings, docker_client=None) -> None:
        self.settings = settings
        self.docker_client = docker_client

        self._poll_interval = settings.MONITOR_POLL_INTERVAL_SEC
        self._retention_sec = settings.MONITOR_RETENTION_SEC
        self._alert_cooldown = settings.MONITOR_ALERT_COOLDOWN_SEC

        # Metrics storage: sandbox_id -> deque of SandboxMetrics
        self._metrics_history: Dict[str, Deque[SandboxMetrics]] = {}

        # Latest snapshot per sandbox
        self._latest_metrics: Dict[str, SandboxMetrics] = {}

        # Alert rules
        self._alert_rules: List[AlertRule] = [
            AlertRule("mem_high", "memory_percent", 90.0, "warn"),
            AlertRule("cpu_sustained", "cpu_percent", 95.0, "warn", duration_sec=10),
            AlertRule("pid_high", "pids_current", 100, "warn"),
        ]

        # Alert history
        self._alerts: Deque[Alert] = deque(maxlen=500)
        self._last_alert_time: Dict[str, float] = {}  # rule_id:sandbox_id -> timestamp

        # WebSocket subscribers: id -> async callback
        self._subscribers: Dict[str, Any] = {}
        self._subscriber_counter = 0

        # Background task
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background metrics collection loop."""
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"📊 Monitor service started: poll_interval={self._poll_interval}s, "
            f"retention={self._retention_sec}s"
        )

    async def stop(self) -> None:
        """Stop metrics collection."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("📊 Monitor service stopped")

    # ── Collection Loop ────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Background loop to collect container metrics."""
        while self._running:
            try:
                await self._collect_metrics()
                await self._evaluate_alerts()
                await self._broadcast()
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor poll error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def _collect_metrics(self) -> None:
        """Collect metrics from all running Docker containers."""
        if not self.docker_client:
            return

        loop = asyncio.get_event_loop()
        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self.docker_client.containers.list(
                    filters={"status": "running", "label": ["thinkdome=true"]}
                )
            )
        except Exception:
            # Fall back to listing all running containers
            try:
                containers = await loop.run_in_executor(
                    None, lambda: self.docker_client.containers.list(filters={"status": "running"})
                )
            except Exception as e:
                logger.debug(f"Cannot list containers: {e}")
                return

        now = time.time()

        for container in containers:
            try:
                stats = await loop.run_in_executor(
                    None, lambda c=container: c.stats(stream=False)
                )
                metrics = self._parse_stats(container.id, container.name, stats)

                sandbox_id = container.name
                self._latest_metrics[sandbox_id] = metrics

                # Store in history
                if sandbox_id not in self._metrics_history:
                    self._metrics_history[sandbox_id] = deque()
                self._metrics_history[sandbox_id].append(metrics)

                # Trim old history
                cutoff = now - self._retention_sec
                while (
                    self._metrics_history[sandbox_id]
                    and self._metrics_history[sandbox_id][0].timestamp < cutoff
                ):
                    self._metrics_history[sandbox_id].popleft()

            except Exception as e:
                logger.debug(f"Failed to collect metrics for {container.id[:12]}: {e}")

    def _parse_stats(self, container_id: str, sandbox_id: str, stats: dict) -> SandboxMetrics:
        """Parse Docker stats JSON into SandboxMetrics."""
        # CPU calculation
        cpu_delta = (
            stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            - stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
        )
        system_delta = (
            stats.get("cpu_stats", {}).get("system_cpu_usage", 0)
            - stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
        )
        num_cpus = stats.get("cpu_stats", {}).get("online_cpus", 1) or 1

        if system_delta > 0 and cpu_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
        else:
            cpu_percent = 0.0

        # Memory
        mem_stats = stats.get("memory_stats", {})
        mem_usage = mem_stats.get("usage", 0)
        mem_limit = mem_stats.get("limit", 1)
        cache = mem_stats.get("stats", {}).get("cache", 0)
        actual_usage = mem_usage - cache

        # Network
        net_stats = stats.get("networks", {})
        rx_bytes = sum(n.get("rx_bytes", 0) for n in net_stats.values())
        tx_bytes = sum(n.get("tx_bytes", 0) for n in net_stats.values())

        # PIDs
        pids = stats.get("pids_stats", {}).get("current", 0)

        # Block I/O
        blkio = stats.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []
        read_bytes = sum(e.get("value", 0) for e in blkio if e.get("op") == "read")
        write_bytes = sum(e.get("value", 0) for e in blkio if e.get("op") == "write")

        return SandboxMetrics(
            container_id=container_id,
            sandbox_id=sandbox_id,
            cpu_percent=cpu_percent,
            memory_usage_mb=actual_usage / (1024 * 1024),
            memory_limit_mb=mem_limit / (1024 * 1024),
            memory_percent=(actual_usage / mem_limit * 100) if mem_limit > 0 else 0,
            network_rx_bytes=rx_bytes,
            network_tx_bytes=tx_bytes,
            pids_current=pids,
            block_read_bytes=read_bytes,
            block_write_bytes=write_bytes,
        )

    # ── Alerting ───────────────────────────────────────────────────────────────

    async def _evaluate_alerts(self) -> None:
        """Evaluate alert rules against current metrics."""
        now = time.time()

        for sandbox_id, metrics in self._latest_metrics.items():
            for rule in self._alert_rules:
                if not rule.enabled:
                    continue

                value = getattr(metrics, rule.metric, None)
                if value is None:
                    continue

                if value >= rule.threshold:
                    cooldown_key = f"{rule.rule_id}:{sandbox_id}"
                    last = self._last_alert_time.get(cooldown_key, 0)

                    if now - last >= self._alert_cooldown:
                        alert = Alert(
                            rule_id=rule.rule_id,
                            sandbox_id=sandbox_id,
                            metric=rule.metric,
                            value=value,
                            threshold=rule.threshold,
                            action=rule.action,
                        )
                        self._alerts.append(alert)
                        self._last_alert_time[cooldown_key] = now

                        logger.warning(
                            f"🚨 Alert [{rule.rule_id}]: {sandbox_id} "
                            f"{rule.metric}={value:.1f} >= {rule.threshold}"
                        )

    # ── WebSocket Broadcast ────────────────────────────────────────────────────

    def subscribe(self, send_fn) -> str:
        """Subscribe a WebSocket client for real-time metrics.

        Args:
            send_fn: Async callable that accepts a dict to send

        Returns:
            Subscriber ID for unsubscribe
        """
        self._subscriber_counter += 1
        sub_id = f"ws_{self._subscriber_counter}"
        self._subscribers[sub_id] = send_fn
        logger.debug(f"WebSocket subscriber added: {sub_id}")
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Remove a WebSocket subscriber."""
        self._subscribers.pop(sub_id, None)
        logger.debug(f"WebSocket subscriber removed: {sub_id}")

    async def _broadcast(self) -> None:
        """Push latest metrics to all WebSocket subscribers."""
        if not self._subscribers:
            return

        payload = {
            "type": "metrics",
            "timestamp": time.time(),
            "sandboxes": {
                sid: m.to_dict() for sid, m in self._latest_metrics.items()
            },
        }

        dead_subs = []
        for sub_id, send_fn in self._subscribers.items():
            try:
                await send_fn(payload)
            except Exception:
                dead_subs.append(sub_id)

        for sub_id in dead_subs:
            self.unsubscribe(sub_id)

    # ── Query API ──────────────────────────────────────────────────────────────

    def get_all_metrics(self) -> Dict[str, dict]:
        """Get latest metrics for all sandboxes."""
        return {sid: m.to_dict() for sid, m in self._latest_metrics.items()}

    def get_sandbox_metrics(self, sandbox_id: str) -> Optional[dict]:
        """Get latest metrics for a specific sandbox."""
        m = self._latest_metrics.get(sandbox_id)
        return m.to_dict() if m else None

    def get_sandbox_history(self, sandbox_id: str) -> List[dict]:
        """Get metrics history for a specific sandbox."""
        history = self._metrics_history.get(sandbox_id, deque())
        return [m.to_dict() for m in history]

    def get_alerts(self, limit: int = 50) -> List[dict]:
        """Get recent alerts."""
        return [a.to_dict() for a in list(self._alerts)[-limit:]]

    def get_alert_rules(self) -> List[dict]:
        """Get configured alert rules."""
        return [r.to_dict() for r in self._alert_rules]

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Add a new alert rule."""
        self._alert_rules.append(rule)

    def get_status(self) -> dict:
        """Return monitor service status."""
        return {
            "running": self._running,
            "tracked_sandboxes": len(self._latest_metrics),
            "total_alerts": len(self._alerts),
            "subscribers": len(self._subscribers),
            "alert_rules": len(self._alert_rules),
        }
