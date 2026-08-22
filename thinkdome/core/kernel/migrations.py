"""ThinkDome Database Migration Engine.

Handles multi-site dynamic version control, schema updates, status audits,
and dynamic rollbacks by executing app-level migration modules.
"""

from __future__ import annotations

import os
import importlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import text

from thinkdome.core.kernel.kernel import Kernel

logger = logging.getLogger(__name__)

from thinkdome.core.config import get_workspace_root

APPS_DIR = get_workspace_root() / "thinkdome" / "apps"


def ensure_migrations_table(kernel: Kernel) -> None:
    """Create the schema_migrations log table if not present in the site database."""
    # Determine dialect type
    is_postgres = "postgres" in str(kernel.db_engine.url)
    
    if is_postgres:
        stmt = (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "id SERIAL PRIMARY KEY,"
            "app_name VARCHAR(255) NOT NULL,"
            "migration_name VARCHAR(255) NOT NULL,"
            "applied_at VARCHAR(255) NOT NULL"
            ")"
        )
    else:
        stmt = (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "app_name VARCHAR(255) NOT NULL,"
            "migration_name VARCHAR(255) NOT NULL,"
            "applied_at VARCHAR(255) NOT NULL"
            ")"
        )
    kernel.db.execute(text(stmt))
    kernel.db.commit()


def get_applied_migrations(kernel: Kernel, app_name: Optional[str] = None) -> List[str]:
    """Retrieve list of migration names already applied to this site database."""
    ensure_migrations_table(kernel)
    if app_name:
        query = "SELECT migration_name FROM schema_migrations WHERE app_name = :app ORDER BY id ASC"
        res = kernel.db.execute(text(query), {"app": app_name}).all()
    else:
        query = "SELECT migration_name FROM schema_migrations ORDER BY id ASC"
        res = kernel.db.execute(text(query)).all()
    return [row[0] for row in res]


# ── Migration Engine ──────────────────────────────────────────────────────────

class MigrationRunner:
    """Manages transaction-safe execution of up/down schema changes."""

    def __init__(self, site_name: str) -> None:
        self.site_name = site_name
        self.kernel = Kernel.get_instance(site_name)
        self.kernel.initialize()

    def migrate(self, target_app: Optional[str] = None) -> None:
        """Run all pending migrations for active apps, logging them to the database."""
        ensure_migrations_table(self.kernel)
        
        apps_to_migrate = [target_app] if target_app else self.kernel.get_installed_apps()
        
        for app_name in apps_to_migrate:
            migrations_dir = APPS_DIR / app_name / "migrations"
            if not migrations_dir.exists():
                continue

            # Discover migration python scripts in sorted order
            scripts = sorted([
                f.stem for f in migrations_dir.glob("*.py")
                if f.name != "__init__.py"
            ])

            applied = get_applied_migrations(self.kernel, app_name)
            pending = [s for s in scripts if s not in applied]

            for migration_name in pending:
                logger.info(f"Applying migration: {app_name}/{migration_name}...")
                
                try:
                    # Dynamically import migration script
                    mod = importlib.import_module(f"thinkdome.apps.{app_name}.migrations.{migration_name}")
                    
                    # Run changes inside a single database transaction block
                    if hasattr(mod, "up"):
                        mod.up(self.kernel.db)
                    
                    # Log application
                    now_str = datetime.now(timezone.utc).isoformat()
                    insert_stmt = (
                        "INSERT INTO schema_migrations (app_name, migration_name, applied_at) "
                        "VALUES (:app, :name, :applied)"
                    )
                    self.kernel.db.execute(text(insert_stmt), {
                        "app": app_name,
                        "name": migration_name,
                        "applied": now_str,
                    })
                    self.kernel.db.commit()
                    logger.info(f"✓ Successfully applied {app_name}/{migration_name}")
                    
                except Exception as e:
                    self.kernel.db.rollback()
                    logger.error(f"Migration {migration_name} failed: {e}")
                    raise RuntimeError(f"Migration error: {e}")

    def rollback(self, target_app: Optional[str] = None) -> None:
        """Revert the last applied migration script for the target app (or globally)."""
        ensure_migrations_table(self.kernel)

        # Get last applied record
        if target_app:
            query = "SELECT id, app_name, migration_name FROM schema_migrations WHERE app_name = :app ORDER BY id DESC LIMIT 1"
            row = self.kernel.db.execute(text(query), {"app": target_app}).first()
        else:
            query = "SELECT id, app_name, migration_name FROM schema_migrations ORDER BY id DESC LIMIT 1"
            row = self.kernel.db.execute(text(query)).first()

        if not row:
            logger.info("No migrations found to rollback.")
            return

        # Cast Row to dictionary to mutate
        record = dict(row._mapping)
        app_name = record["app_name"]
        migration_name = record["migration_name"]

        logger.info(f"Rolling back migration: {app_name}/{migration_name}...")

        try:
            # Dynamically import and run teardown changes
            mod = importlib.import_module(f"thinkdome.apps.{app_name}.migrations.{migration_name}")
            if hasattr(mod, "down"):
                mod.down(self.kernel.db)

            # Purge record from logs
            delete_stmt = "DELETE FROM schema_migrations WHERE id = :id"
            self.kernel.db.execute(text(delete_stmt), {"id": record["id"]})
            self.kernel.db.commit()
            logger.info(f"✓ Successfully rolled back {app_name}/{migration_name}")
            
        except Exception as e:
            self.kernel.db.rollback()
            logger.error(f"Rollback failed: {e}")
            raise RuntimeError(f"Rollback error: {e}")

    def status(self) -> List[Dict[str, Any]]:
        """Return applied status mappings for all discoverable app migrations."""
        ensure_migrations_table(self.kernel)
        status_report = []

        for app_name in self.kernel.get_installed_apps():
            migrations_dir = APPS_DIR / app_name / "migrations"
            if not migrations_dir.exists():
                continue

            scripts = sorted([
                f.stem for f in migrations_dir.glob("*.py")
                if f.name != "__init__.py"
            ])
            applied = get_applied_migrations(self.kernel, app_name)

            for script in scripts:
                status_report.append({
                    "app": app_name,
                    "migration": script,
                    "status": "Applied" if script in applied else "Pending",
                })
        return status_report
