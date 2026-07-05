"""Prometheus metrics registry and middleware for ThinkDome."""

from __future__ import annotations

import time
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

# Define core metrics
REQUESTS_TOTAL = Counter(
    "thinkdome_requests_total",
    "Total number of API and tool execution requests received",
    ["endpoint", "tool", "role", "status"]
)

REQUEST_DURATION = Histogram(
    "thinkdome_request_duration_seconds",
    "API and tool request latency in seconds",
    ["endpoint", "tool", "role"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
)

ACTIVE_SANDBOXES = Gauge(
    "thinkdome_active_sandboxes",
    "Current number of active sandbox environments",
    ["backend_type"]
)

RABBITMQ_QUEUE_DEPTH = Gauge(
    "thinkdome_rabbitmq_queue_depth",
    "RabbitMQ orchestration queue depth",
    ["queue_name"]
)

POOL_HIT_RATE = Gauge(
    "thinkdome_pool_hit_rate",
    "Pre-warmed sandbox pool acquisition cache hit rate"
)

EXECUTOR_BACKEND_INFO = Gauge(
    "thinkdome_executor_backend",
    "Information about the active executor backend",
    ["backend"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for capturing request count and duration metrics."""

    async def dispatch(self, request: Request, call_next):
        # Exclude prometheus metrics scraping endpoint itself to prevent loop inflation
        if request.url.path == "/v1/metrics":
            return await call_next(request)

        start_time = time.monotonic()
        endpoint = request.url.path
        
        # Default labels
        tool = "none"
        role = "guest"
        
        # Try to extract tool and role details if present in headers or state
        if hasattr(request.state, "user") and request.state.user:
            role = request.state.user.get("role", "guest")

        try:
            response = await call_next(request)
            status_code = response.status_code
            status = "success" if status_code < 400 else "error"
            
            REQUESTS_TOTAL.labels(
                endpoint=endpoint,
                tool=tool,
                role=role,
                status=status
            ).inc()
            
            duration = time.monotonic() - start_time
            REQUEST_DURATION.labels(
                endpoint=endpoint,
                tool=tool,
                role=role
            ).observe(duration)
            
            return response
            
        except Exception as e:
            REQUESTS_TOTAL.labels(
                endpoint=endpoint,
                tool=tool,
                role=role,
                status="failure"
            ).inc()
            raise e


def setup_metrics(app: FastAPI, backend_name: str) -> None:
    """Setup Prometheus middleware and configure backend info gauge."""
    app.add_middleware(PrometheusMiddleware)
    EXECUTOR_BACKEND_INFO.labels(backend=backend_name).set(1)
