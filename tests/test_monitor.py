"""Unit tests for the monitoring and alerting service."""

import pytest
import asyncio
from thinkdome.modules.monitoring.monitor_service import MonitorService, AlertRule, SandboxMetrics
from thinkdome.core.config import Settings


@pytest.fixture
def mock_settings():
    settings = Settings()
    settings.MONITOR_POLL_INTERVAL_SEC = 0.5
    settings.MONITOR_RETENTION_SEC = 5
    settings.MONITOR_ALERT_COOLDOWN_SEC = 2
    return settings


@pytest.mark.asyncio
async def test_monitor_initialization(mock_settings):
    monitor = MonitorService(mock_settings, docker_client=None)
    await monitor.start()
    
    status = monitor.get_status()
    assert status["running"] is True
    assert status["tracked_sandboxes"] == 0
    assert status["total_alerts"] == 0
    
    await monitor.stop()


@pytest.mark.asyncio
async def test_monitor_alert_evaluation(mock_settings):
    monitor = MonitorService(mock_settings, docker_client=None)
    await monitor.start()

    # Manually inject high metrics snapshot
    sandbox_id = "test-sandbox-id"
    metrics = SandboxMetrics(
        container_id="cont123",
        sandbox_id=sandbox_id,
        cpu_percent=10.0,
        memory_usage_mb=95.0,
        memory_limit_mb=100.0,
        memory_percent=95.0,  # > 90% threshold rule
        pids_current=5,
    )
    monitor._latest_metrics[sandbox_id] = metrics

    # Manually trigger alert evaluation
    await monitor._evaluate_alerts()
    
    alerts = monitor.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "mem_high"
    assert alerts[0]["sandbox_id"] == sandbox_id
    assert alerts[0]["metric"] == "memory_percent"
    assert alerts[0]["value"] == 95.0

    # Ensure alert deduplication cooldown holds
    await monitor._evaluate_alerts()
    assert len(monitor.get_alerts()) == 1  # No duplicate alert within cooldown

    await monitor.stop()


@pytest.mark.asyncio
async def test_monitor_websocket_subscription(mock_settings):
    monitor = MonitorService(mock_settings, docker_client=None)
    await monitor.start()

    broadcasts = []

    async def mock_ws_send(payload):
        broadcasts.append(payload)

    # 1. Subscribe client
    sub_id = monitor.subscribe(mock_ws_send)
    assert len(monitor._subscribers) == 1

    # Inject mock metric
    sandbox_id = "test-sandbox"
    monitor._latest_metrics[sandbox_id] = SandboxMetrics(
        container_id="cont123",
        sandbox_id=sandbox_id,
        cpu_percent=5.0
    )

    # 2. Trigger broadcast
    await monitor._broadcast()
    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "metrics"
    assert sandbox_id in broadcasts[0]["sandboxes"]

    # 3. Unsubscribe client
    monitor.unsubscribe(sub_id)
    assert len(monitor._subscribers) == 0

    await monitor.stop()
