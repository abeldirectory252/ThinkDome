"""ThinkDome Database Migration Engine.

Handles multi-site dynamic version control, schema updates, status audits,
and dynamic rollbacks by executing app-level migration modules.
"""

from __future__ import annotations

import os
import importlib
import logging
import threading
import shutil
import re
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
    kernel.db.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_schema_migrations_app_name "
        "ON schema_migrations (app_name, migration_name)"
    ))
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

    def __init__(self, site_name: Optional[str] = None, kernel: Optional[Kernel] = None) -> None:
        if kernel is not None:
            self.kernel = kernel
            self.site_name = kernel.site_name
            return
        if not site_name:
            site_name = os.environ.get("THINKDOME_SITE", "think.local")
        self.site_name = site_name
        self.kernel = Kernel.get_instance(site_name)
        self.kernel.initialize()

    def migrate(self, target_app: Optional[str] = None) -> Optional[Path]:
        """Run pending migrations under a process-wide startup lock."""
        with self._process_lock:
            return self._migrate_locked(target_app)

    def backup_database(self) -> Optional[Path]:
        """Create a durable SQLite backup before applying migrations."""
        url = str(self.kernel.db_engine.url)
        if not url.startswith("sqlite:///"):
            return None
        source = Path(url[10:])
        if not source.exists():
            return None
        backup_dir = self.kernel.site_dir / "private" / "backups" / "migrations"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{source.stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db"
        self.kernel.db.execute(text("PRAGMA wal_checkpoint(FULL)"))
        self.kernel.db.commit()
        shutil.copy2(source, target)
        return target

    def make_migration(self, app_name: str, name: str) -> Path:
        """Create an explicit, reviewable migration skeleton for an app."""
        if not re.fullmatch(r"[A-Za-z0-9_]+", app_name) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError("app and migration names may contain only letters, numbers, and underscores")
        migration_dir = APPS_DIR / app_name / "migrations"
        if not migration_dir.is_dir():
            raise FileNotFoundError(f"Migration directory not found: {migration_dir}")
        numbers = [int(path.name.split("_", 1)[0]) for path in migration_dir.glob("[0-9][0-9][0-9][0-9]_*.py") if path.name[:4].isdigit()]
        number = max(numbers, default=0) + 1
        path = migration_dir / f"{number:04d}_{name}.py"
        path.write_text('''"""Generated migration; implement the schema transition before running migrate."""\n\n\ndef up(db) -> None:\n    """Apply this migration."""\n    pass\n\n\ndef down(db) -> None:\n    """Rollback this migration when safely supported."""\n    pass\n''', encoding="utf-8")
        return path

    def _migrate_locked(self, target_app: Optional[str] = None) -> Optional[Path]:
        """Run all pending migrations for active apps, logging them to the database."""
        ensure_migrations_table(self.kernel)
        backup = self.backup_database()
        if backup:
            logger.info("Migration backup created at %s", backup)
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
        return backup

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
    _process_lock = threading.RLock()
