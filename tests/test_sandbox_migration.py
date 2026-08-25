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


def test_legacy_sandbox_rows_are_migrated_into_orm_table():
    migration = importlib.import_module("thinkdome.apps.sandbox.migrations.0003_merge_legacy_sandboxes")
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    from thinkdome.apps.sandbox.models import Sandbox
    from thinkdome.core.orm.orm import Base
    Base.metadata.create_all(engine)
    session.execute(text("CREATE TABLE sandboxes (sandbox_id TEXT PRIMARY KEY, name TEXT, owner TEXT, status TEXT, backend_type TEXT, memory_mb INTEGER, cpu_cores REAL, gpu_count INTEGER, network_enabled INTEGER, storage_quota_mb INTEGER)"))
    session.execute(text("INSERT INTO sandboxes VALUES ('legacy-1','legacy','owner','active','docker',256,1.0,0,0,10240)"))
    session.commit()
    migration.up(session)
    assert Sandbox.get("legacy-1") is not None
    assert not inspect(engine).has_table("sandboxes")
