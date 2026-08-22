"""Add control-plane fields needed by durable sandbox reservations."""

from sqlalchemy import inspect, text


def up(db) -> None:
    """Add columns conservatively so existing SQLite/Postgres sites can upgrade."""
    # Importing the models registers their tables with the custom ORM metadata;
    # create_all only creates missing tables and does not overwrite data.
    from thinkdome.apps.sandbox import models  # noqa: F401
    from thinkdome.core.orm.orm import Base

    Base.metadata.create_all(db.bind)
    inspector = inspect(db.bind)
    columns = (
        {column["name"] for column in inspector.get_columns("sandboxes")}
        if inspector.has_table("sandboxes")
        else set()
    )
    if columns and "pids_limit" not in columns:
        db.execute(text("ALTER TABLE sandboxes ADD COLUMN pids_limit INTEGER DEFAULT 64"))
    indexes = {
        "uq_projects_project_id": ("projects", "project_id"),
        "uq_executionnodes_node_id": ("executionnodes", "node_id"),
        "uq_sandboxplacements_sandbox_id": ("sandboxplacements", "sandbox_id"),
        "uq_idempotencyrecords_scope": (
            "idempotencyrecords", "organization_id, operation, idempotency_key"
        ),
    }
    for name, (table, fields) in indexes.items():
        if inspector.has_table(table):
            db.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({fields})"))
    db.commit()


def down(db) -> None:
    """Column removal is intentionally unsupported across SQLite versions."""
    return None
