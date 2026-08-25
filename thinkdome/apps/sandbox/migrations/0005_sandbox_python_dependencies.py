"""Add persisted Python dependency requests to sandbox records."""

from sqlalchemy import inspect, text


def up(db) -> None:
    inspector = inspect(db.bind)
    table = "sandboxs" if inspector.has_table("sandboxs") else "sandboxes"
    if not inspector.has_table(table):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "python_dependencies" not in columns:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN python_dependencies TEXT DEFAULT '[]'"))
        db.commit()


def down(db) -> None:
    return None
