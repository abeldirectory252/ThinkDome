"""ORM model for persisted platform configuration."""

from thinkdome.core.orm.orm import Model, StringField, TextField


class AdminConfig(Model):
    __tablename__ = "admin_configs"
    __primary_key__ = "config_key"
    __omit_soft_delete__ = True

    config_key = StringField(required=True)
    config_value = TextField(required=True)
    updated_at = StringField()
    updated_by = StringField(required=True)
