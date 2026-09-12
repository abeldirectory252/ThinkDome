"""ORM models for the legacy observability tables.

These tables predate the RBAC ORM and intentionally do not have ThinkDome's
soft-delete column.  They remain mapped here so read paths do not need SQL.
"""

from thinkdome.core.orm.orm import FloatField, Model, StringField, TextField


class LegacyAuditLog(Model):
    __tablename__ = "audit_logs"
    __omit_soft_delete__ = True

    timestamp = StringField()
    actor = StringField(required=True)
    action = StringField(required=True)
    ip_address = StringField(default="0.0.0.0")
    details = TextField(default="{}")
    trace_id = StringField()


class RequestLog(Model):
    __tablename__ = "request_logs"
    __omit_soft_delete__ = True

    request_id = StringField(required=True)
    timestamp = StringField()
    display_name = StringField(required=True)
    role = StringField(required=True)
    client_ip = StringField(default="0.0.0.0")
    tool_name = StringField(required=True)
    request_payload = TextField(default="{}")
    response_payload = TextField(default="{}")
    status = StringField(default="pending")
    duration_ms = FloatField(default=0.0)
    sandbox_id = StringField()
    trace_id = StringField()
    worker_id = StringField()
