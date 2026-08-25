import importlib

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


def test_control_plane_migration_creates_durable_tables():
    migration = importlib.import_module("thinkdome.apps.sandbox.migrations.0001_control_plane")
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    migration.up(session)
    tables = set(inspect(engine).get_table_names())
    assert {"organizations", "projects", "executionnodes", "sandboxplacements", "idempotencyrecords"} <= tables


def test_storage_quota_migration_updates_legacy_orm_table():
    migration = importlib.import_module("thinkdome.apps.sandbox.migrations.0002_storage_quota")
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    session.execute(text("CREATE TABLE sandboxs (id VARCHAR PRIMARY KEY, name VARCHAR)"))
    session.commit()
    migration.up(session)
    columns = {column["name"] for column in inspect(engine).get_columns("sandboxs")}
    assert "storage_quota_mb" in columns
