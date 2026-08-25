"""Add the sandbox storage quota column to existing ORM databases."""

from sqlalchemy import inspect, text


def up(db) -> None:
    """Apply the additive storage quota change on every supported database."""
    inspector = inspect(db.bind)
    table = "sandboxs" if inspector.has_table("sandboxs") else "sandboxes"
    if not inspector.has_table(table):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "storage_quota_mb" not in columns:
        # The table name comes only from this fixed internal allowlist.
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN storage_quota_mb INTEGER DEFAULT 10240"))
        db.commit()


def down(db) -> None:
    """Column removal is intentionally unsupported for SQLite compatibility."""
    return None
