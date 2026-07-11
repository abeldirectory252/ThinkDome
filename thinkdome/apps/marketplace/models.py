"""Marketplace app models."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    BooleanField,
)


class AppExtension(Model):
    """Registry record for extensions and plugins installed from external repositories."""

    name = StringField(required=True)
    description = StringField(default="")
    version = StringField(default="1.0.0")
    source_url = StringField(default="")
    installed = BooleanField(default=False)
    author = StringField(default="anonymous")
