"""Workflow and WorkflowExecution models."""

from __future__ import annotations

from thinkdome.core.orm.orm import (
    Model,
    StringField,
    IntegerField,
    BooleanField,
    SelectField,
)


class Workflow(Model):
    """Automation pipeline definition with ordered step nodes and conditional edges."""

    name = StringField(required=True)
    description = StringField(default="")
    trigger_event = StringField(default="manual")     # Event name that auto-starts this workflow
    nodes = StringField(default="[]")                  # JSON array of node definitions
    edges = StringField(default="[]")                  # JSON array of edge connections
    is_active = BooleanField(default=True)
    owner = StringField(required=True)
    version = IntegerField(default=1)


class WorkflowExecution(Model):
    """Runtime state tracker for a single execution of a Workflow."""

    workflow_id = StringField(required=True)
    trigger_data = StringField(default="{}")            # JSON input payload
    current_node = StringField(default="")
    status = SelectField(
        choices=["Pending", "Running", "WaitingApproval", "Completed", "Failed", "Cancelled"],
        default="Pending",
    )
    step_results = StringField(default="[]")            # JSON array of per-node outputs
    error_message = StringField(default="")
    started_by = StringField(default="system")
