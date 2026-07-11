"""Agent Model and lifecycle definitions."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    BooleanField,
    SelectField,
)


class Agent(Model):
    """AI or automation worker entity with tool permissions and sandbox binding."""

    name = StringField(required=True)
    model = StringField(default="gpt-4o")
    tools = StringField(default="[]")          # JSON list of allowed tool names
    memory = StringField(default="{}")          # JSON blob of persistent memory state
    permissions = StringField(default="[]")     # JSON list of permission grants
    sandbox_id = StringField()                  # FK to Sandbox
    max_steps = IntegerField(default=25)
    timeout_sec = IntegerField(default=300)
    status = SelectField(
        choices=["Created", "Ready", "Executing", "Completed", "Failed"],
        default="Created",
    )
    owner = StringField(required=True)
    result = StringField(default="")            # Final output after completion
    error_message = StringField(default="")
