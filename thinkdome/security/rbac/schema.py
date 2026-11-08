"""Database Schema Initializer for Enterprise RBAC Module.

Leverages ThinkDome's custom ORM model metadata bindings to create tables automatically.
Includes auto-migration to add newly declared columns to existing tables.
"""

from __future__ import annotations

import logging
from thinkdome.platform.database.service import DatabaseService
from thinkdome.core.orm.orm import Base
import thinkdome.security.rbac.models  # Trigger model class registration

logger = logging.getLogger(__name__)


def _add_missing_columns(engine) -> None:
    """Auto-migrate: add columns declared in ORM models but absent from existing tables."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    for table_name, table_obj in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for col in table_obj.columns:
            if col.name not in existing_cols:
                col_type = col.type.compile(dialect=engine.dialect)
                default_clause = ""
                if col.default is not None:
                    default_val = col.default.arg
                    if callable(default_val):
                        default_clause = " DEFAULT ''"
                    elif isinstance(default_val, bool):
                        default_clause = f" DEFAULT {1 if default_val else 0}"
                    elif isinstance(default_val, (int, float)):
                        default_clause = f" DEFAULT {default_val}"
                    elif isinstance(default_val, str):
                        default_clause = f" DEFAULT '{default_val}'"
                try:
                    with engine.connect() as conn:
                        conn.execute(text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                        ))
                        conn.commit()
                    logger.info("Auto-migrated column %s.%s", table_name, col.name)
                except Exception as col_err:
                    logger.debug("Column %s.%s migration skipped: %s", table_name, col.name, col_err)


def initialize_rbac_schema(db: DatabaseService) -> None:
    """Ensure all RBAC SQLAlchemy metadata tables exist in the current database engine."""
    try:
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.current()
        if not kernel.initialized:
            kernel.initialize()
        Base.metadata.create_all(kernel.db_engine)
        # Auto-migrate: add any newly declared columns to existing tables
        _add_missing_columns(kernel.db_engine)
        # ``create_all`` does not add a newly-declared index to an existing
        # table. Create ORM metadata indexes explicitly, with checkfirst,
        # so upgrades receive the same lookup optimizations as fresh sites.
        for table in ("rbac_users", "rbac_roles", "rbac_user_roles", "rbac_role_profiles", "rbac_role_profile_roles", "rbac_user_role_profiles"):
            if table in Base.metadata.tables:
                for index in Base.metadata.tables[table].indexes:
                    index.create(kernel.db_engine, checkfirst=True)
        logger.info("Enterprise RBAC Schema tables verified and initialized via ThinkDome ORM.")
    except Exception as e:
        logger.warning(f"Failed to initialize schema via Kernel engine: {e}. Executing table creation on DB service.")
        # Fallback DDL execution
        try:
            for table in Base.metadata.sorted_tables:
                try:
                    table.create(kernel.db_engine, checkfirst=True)
                except Exception:
                    pass
        except Exception:
            pass
