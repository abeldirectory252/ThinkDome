"""Monitoring models for resource tracking and cost accounting."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    FloatField,
)


class ResourceMetric(Model):
    """Point-in-time resource usage snapshot for a sandbox or agent."""

    sandbox_id = StringField()
    agent_id = StringField()
    cpu_percent = FloatField(default=0.0)
    memory_mb = IntegerField(default=0)
    gpu_percent = FloatField(default=0.0)
    storage_mb = IntegerField(default=0)
    network_bytes_in = IntegerField(default=0)
    network_bytes_out = IntegerField(default=0)
    cost_usd = FloatField(default=0.0)
    recorded_at = StringField(default="")
