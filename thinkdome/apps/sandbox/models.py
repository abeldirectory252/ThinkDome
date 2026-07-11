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
    runtime = SelectField(choices=["docker", "kubernetes", "subprocess"], default="docker")
    image = StringField(default="python:3.12-slim")
    cpu_limit = FloatField(default=1.0)
    memory_limit = IntegerField(default=256)
    gpu_limit = IntegerField(default=0)
    storage_limit = IntegerField(default=10)
    network_enabled = BooleanField(default=False)
    status = SelectField(
        choices=["Created", "Provisioning", "Running", "Paused", "Stopped", "Destroyed"],
        default="Created",
    )
    owner = StringField(required=True)
