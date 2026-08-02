"""OpenTelemetry distributed tracing setup for ThinkDome.

Instruments FastAPI, database calls, HTTP queries, and message broker tasks
to provide full visibility across worker nodes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str, otlp_endpoint: str, enabled: bool = False) -> None:
    """Initialize OpenTelemetry tracer provider with OTLP exporter if enabled."""
    if not enabled:
        logger.info("🔭 OpenTelemetry tracing is disabled")
        trace.set_tracer_provider(trace.NoOpTracerProvider())
        return

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        
        resource = Resource.create(attributes={
            "service.name": service_name,
            "compose_service": service_name
        })

        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info(f"🔭 OpenTelemetry tracing enabled pointing to {otlp_endpoint}")

    except Exception as e:
        logger.warning(f"🔭 Failed to initialize OpenTelemetry exporter: {e}. Falling back to NoOp provider.")
        trace.set_tracer_provider(trace.NoOpTracerProvider())


def get_tracer(name: str = "thinkdome") -> trace.Tracer:
    """Get or create a tracer instance."""
    return trace.get_tracer(name)


def get_current_span_context() -> Optional[trace.SpanContext]:
    """Get active span context for header propagation."""
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        return current_span.get_span_context()
    return None
