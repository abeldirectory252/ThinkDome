import importlib

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


def test_control_plane_migration_creates_durable_tables():
    migration = importlib.import_module("thinkdome.apps.sandbox.migrations.0001_control_plane")
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    migration.up(session)
    tables = set(inspect(engine).get_table_names())
    assert {"organizations", "projects", "executionnodes", "sandboxplacements", "idempotencyrecords"} <= tables
