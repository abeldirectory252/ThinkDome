"""ORM entities for administrator-defined Workspace Desk configuration."""

from thinkdome.core.orm.orm import IntegerField, Model, StringField, TextField


class WorkspaceRecord(Model):
    __tablename__ = "workspace_records"

    name = StringField(required=True)
    status = StringField(required=True, default="active")
    created_at = StringField(required=True)
    ttl_seconds = IntegerField(required=True)
    quota_mb = IntegerField(required=True)
    owner_id = StringField(required=True, indexed=True)


class WorkspaceDeskPage(Model):
    __tablename__ = "workspace_desk_pages"
    __unique_together__ = ("workspace_id", "page_id")

    workspace_id = StringField(required=True, indexed=True)
    page_id = StringField(required=True)
    title = StringField(required=True)
    allowed_roles_json = TextField(required=True, default="[]")
    blocks_json = TextField(required=True, default="[]")


class WorkspaceDeskMenu(Model):
    __tablename__ = "workspace_desk_menus"
    __unique_together__ = ("workspace_id",)

    workspace_id = StringField(required=True, indexed=True)
    sections_json = TextField(required=True, default="[]")
