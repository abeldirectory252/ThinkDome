"""Sandbox Model definitions."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    FloatField,
    BooleanField,
    SelectField,
)


class Sandbox(Model):
    """Execution sandbox entity mapping runtime configurations to the database."""

    name = StringField(required=True)
    runtime = SelectField(choices=["docker", "kubernetes", "subprocess", "microvm"], default="docker")
    image = StringField(default="python:3.12-slim")
    cpu_limit = FloatField(default=1.0)
    memory_limit = IntegerField(default=256)
    pids_limit = IntegerField(default=64)
    gpu_limit = IntegerField(default=0)
    storage_limit = IntegerField(default=10)
    storage_quota_mb = IntegerField(default=10240)
    network_enabled = BooleanField(default=False)
    status = SelectField(
        choices=["Created", "Provisioning", "Running", "Paused", "Stopped", "Destroyed"],
        default="Created",
    )
    owner = StringField(required=True)
    organization_id = StringField(default="")
    project_id = StringField(default="")
    node_id = StringField(default="")
    placement_version = IntegerField(default=0)


class Organization(Model):
    """Tenant boundary for all control-plane resources."""

    organization_id = StringField(required=True)
    name = StringField(required=True)
    status = SelectField(choices=["active", "suspended", "deleted"], default="active")


class Project(Model):
    """Isolation and quota boundary within an organization."""

    project_id = StringField(required=True)
    organization_id = StringField(required=True)
    name = StringField(required=True)
    status = SelectField(choices=["active", "suspended", "deleted"], default="active")
    max_sandboxes = IntegerField(default=10)
    max_cpu_millis = IntegerField(default=4000)
    max_memory_bytes = IntegerField(default=8_589_934_592)
    __unique_together__ = ("project_id",)


class ExecutionNode(Model):
    """Node-local orchestrator registration and capacity lease."""

    node_id = StringField(required=True)
    region = StringField(default="default")
    state = SelectField(choices=["registering", "ready", "draining", "offline"], default="registering")
    capacity_json = StringField(default="{}")
    orchestrator_version = StringField(required=True)
    lease_expires_at = FloatField(default=0.0)
    __unique_together__ = ("node_id",)


class SandboxPlacement(Model):
    """Durable placement decision with an optimistic version."""

    sandbox_id = StringField(required=True)
    organization_id = StringField(required=True)
    project_id = StringField(required=True)
    node_id = StringField(required=True)
    region = StringField(default="default")
    placement_version = IntegerField(default=1)
    lease_expires_at = FloatField(default=0.0)
    __unique_together__ = ("sandbox_id",)


class IdempotencyRecord(Model):
    """Replay-safe operation key scoped to an organization and operation."""

    organization_id = StringField(required=True)
    project_id = StringField(required=True)
    idempotency_key = StringField(required=True)
    operation = StringField(required=True)
    resource_id = StringField(default="")
    response_json = StringField(default="{}")
    expires_at = FloatField(default=0.0)
    __unique_together__ = ("organization_id", "operation", "idempotency_key")


class Snapshot(Model):
    """Snapshot checkpoint entity mapping state snapshots to the database for backtracking."""

    snapshot_id = StringField(primary_key=True)
    sandbox_id = StringField(required=True)
    name = StringField(default="")
    tag = StringField(default="")
    description = StringField(default="")
    created_at = FloatField()
    state_dir = StringField(default="")
    parent_snapshot_id = StringField(default="")
    owner = StringField(default="anonymous")


class SystemSetting(Model):
    """Global system & infrastructure settings entity mapped to database via ORM schema."""

    key = StringField(required=True)
    value = StringField(default="")
    category = StringField(default="general")
    db_engine = StringField(default="sqlite")
    db_connection_url = StringField(default="sqlite:///sites/think.local/storage/thinkbox.db")
    db_max_connections = IntegerField(default=20)
    db_pool_size = IntegerField(default=5)
    db_echo_sql = BooleanField(default=False)
    rabbitmq_uri = StringField(default="amqp://guest:guest@localhost:5672/")
    redis_url = StringField(default="redis://127.0.0.1:6379/0")
    smtp_host = StringField(default="smtp.sendgrid.net")
    smtp_port = IntegerField(default=587)
    timezone = StringField(default="UTC")
    __unique_together__ = ("key",)
