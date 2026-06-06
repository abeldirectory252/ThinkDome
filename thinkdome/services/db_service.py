"""Database service for SQLite operations and audit logging."""

from __future__ import annotations

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict, List
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)

class DatabaseService:
    """Manages SQLite storage for authentication, request logs, and audits."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "thinkbox.db"
        self._initialize_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection to the SQLite database with a busy timeout."""
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_db(self) -> None:
        """Create database tables if they do not exist."""
        logger.info(f"Initializing SQLite database at: {self.db_path}")
        with self._get_connection() as conn:
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            
            # Users Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    hashed_password TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # API Keys Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    token TEXT PRIMARY KEY,
                    key_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    token_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL
                );
            """)

            # Request Logs Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    client_ip TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    request_payload TEXT NOT NULL,
                    response_payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms REAL NOT NULL
                );
            """)

            # Audit Logs Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    details TEXT NOT NULL
                );
            """)

            # Sandboxes Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sandboxes (
                    sandbox_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    memory_mb INTEGER NOT NULL DEFAULT 256,
                    cpu_cores REAL NOT NULL DEFAULT 1.0,
                    timeout_sec INTEGER NOT NULL DEFAULT 30,
                    network_enabled INTEGER NOT NULL DEFAULT 0,
                    cost_per_hour REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );
            """)
            conn.commit()
        logger.info("SQLite database tables verified successfully.")

    # Generic execution helpers to abstract DB interactions
    def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a write query."""
        with self._get_connection() as conn:
            conn.execute(query, params)
            conn.commit()

    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all matching rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch a single matching row."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    # Audit logging helper
    def log_audit(self, actor: str, action: str, ip_address: str, details: Dict[str, Any]) -> None:
        """Create a persistent record of an administrative or security event."""
        try:
            timestamp = datetime.utcnow().isoformat()
            details_str = json.dumps(details)
            self.execute(
                """
                INSERT INTO audit_logs (timestamp, actor, action, ip_address, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, actor, action, ip_address, details_str)
            )
            logger.info(f"Audit Log: {actor} performed {action}. Details: {details_str}")
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")

    # ── SANDBOX CRUD ──

    def create_sandbox(self, sandbox_id: str, name: str, owner: str,
                       memory_mb: int, cpu_cores: float, timeout_sec: int,
                       network_enabled: bool, cost_per_hour: float) -> Dict[str, Any]:
        """Insert a new sandbox environment record."""
        timestamp = datetime.utcnow().isoformat()
        self.execute(
            """
            INSERT OR REPLACE INTO sandboxes (sandbox_id, name, owner, status, memory_mb, cpu_cores,
                                              timeout_sec, network_enabled, cost_per_hour, created_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (sandbox_id, name, owner, memory_mb, cpu_cores, timeout_sec,
             1 if network_enabled else 0, cost_per_hour, timestamp)
        )
        return self.get_sandbox(sandbox_id)

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single sandbox by ID."""
        row = self.fetch_one("SELECT * FROM sandboxes WHERE sandbox_id = ?", (sandbox_id,))
        if row:
            row = dict(row)
            row["network_enabled"] = bool(row["network_enabled"])
        return row

    def list_sandboxes(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all sandboxes, optionally filtered by owner."""
        if owner:
            rows = self.fetch_all(
                "SELECT * FROM sandboxes WHERE owner = ? ORDER BY created_at DESC", (owner,)
            )
        else:
            rows = self.fetch_all("SELECT * FROM sandboxes ORDER BY created_at DESC")
        for r in rows:
            r["network_enabled"] = bool(r["network_enabled"])
        return rows

    def update_sandbox_status(self, sandbox_id: str, status: str) -> bool:
        """Toggle sandbox active/stopped status."""
        existing = self.get_sandbox(sandbox_id)
        if not existing:
            return False
        self.execute(
            "UPDATE sandboxes SET status = ? WHERE sandbox_id = ?",
            (status, sandbox_id)
        )
        return True

    def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox record."""
        existing = self.get_sandbox(sandbox_id)
        if not existing:
            return False
        self.execute("DELETE FROM sandboxes WHERE sandbox_id = ?", (sandbox_id,))
        return True

