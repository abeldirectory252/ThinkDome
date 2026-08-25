"""Add durable lease expiration timestamps to sandbox records."""

from sqlalchemy import inspect, text


def up(db) -> None:
    inspector = inspect(db.bind)
    table = "sandboxs" if inspector.has_table("sandboxs") else "sandboxes"
    if not inspector.has_table(table):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "expires_at" not in columns:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN expires_at REAL DEFAULT 0"))
        db.commit()


def down(db) -> None:
    # SQLite cannot safely drop columns across supported versions.
    return None
