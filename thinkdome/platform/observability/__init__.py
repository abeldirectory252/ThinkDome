"""Observability domain — metrics, tracing & resource monitoring.

Subdirectories:
  - metrics/    : Prometheus metrics setup & definitions
  - tracing/    : OpenTelemetry distributed tracing
  - monitoring/ : MonitorService (health, system resources, alerts)
  - api/        : REST API routers (health, monitor, observability)
"""

from thinkdome.platform.observability.monitoring.service import MonitorService
from thinkdome.platform.observability.metrics.prometheus import setup_metrics
from thinkdome.platform.observability.tracing.telemetry import setup_tracing

__all__ = [
    "MonitorService",
    "setup_metrics",
    "setup_tracing",
]
