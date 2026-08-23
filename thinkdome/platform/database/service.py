"""Centralized Database Service with hybrid SQLite / PostgreSQL support.

Provides a synchronous API to the application and unit tests (avoiding massive
async refactoring of auth/billing services), while internally delegating to
either local SQLite (for dev/test) or centralized PostgreSQL via asyncpg
run on a dedicated event loop thread.

Automatically translates SQLite placeholder syntax ('?') to PostgreSQL syntax ('$1')
when running in Postgres mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
from thinkdome.core.config import Settings

logger = logging.getLogger(__name__)


class AsyncLoopThread(threading.Thread):
    """Background thread running a dedicated asyncio event loop for asyncpg."""
    def __init__(self):
        super().__init__(daemon=True, name="db-async-loop")
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


# ── Schema SQL for both engines ──────────────────────────────────────────────────

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    hashed_password TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_keys (
    token TEXT PRIMARY KEY,
    key_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    token_type TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    status TEXT DEFAULT 'active',
    masked_token TEXT
);

CREATE TABLE IF NOT EXISTS sandboxes (
    sandbox_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    backend_type TEXT DEFAULT 'docker',
    memory_mb INTEGER DEFAULT 256,
    cpu_cores REAL DEFAULT 1.0,
    gpu_count INTEGER DEFAULT 0,
    timeout_sec INTEGER DEFAULT 30,
    network_enabled INTEGER DEFAULT 0,
    cost_per_hour REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    client_ip TEXT DEFAULT '0.0.0.0',
    tool_name TEXT NOT NULL,
    request_payload TEXT DEFAULT '{}',
    response_payload TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    duration_ms REAL DEFAULT 0.0,
    sandbox_id TEXT,
    trace_id TEXT,
    worker_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    ip_address TEXT DEFAULT '0.0.0.0',
    details TEXT DEFAULT '{}',
    trace_id TEXT
);

CREATE TABLE IF NOT EXISTS credential_vault (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    sandbox_id TEXT NOT NULL,
    key_name TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, sandbox_id, key_name)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS sandbox_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_image TEXT NOT NULL,
    runtime TEXT DEFAULT 'python',
    vcpus REAL DEFAULT 1.0,
    memory_mb INTEGER DEFAULT 512,
    network_policy_id TEXT DEFAULT 'blocked',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_configs (
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT NOT NULL
);
"""

POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    hashed_password TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    token TEXT PRIMARY KEY,
    key_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    token_type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    status TEXT DEFAULT 'active',
    masked_token TEXT
);

CREATE TABLE IF NOT EXISTS sandboxes (
    sandbox_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    backend_type TEXT DEFAULT 'docker',
    memory_mb INTEGER DEFAULT 256,
    cpu_cores REAL DEFAULT 1.0,
    gpu_count INTEGER DEFAULT 0,
    timeout_sec INTEGER DEFAULT 30,
    network_enabled BOOLEAN DEFAULT FALSE,
    cost_per_hour REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS request_logs (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    client_ip TEXT DEFAULT '0.0.0.0',
    tool_name TEXT NOT NULL,
    request_payload TEXT DEFAULT '{}',
    response_payload TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    duration_ms REAL DEFAULT 0.0,
    sandbox_id TEXT,
    trace_id TEXT,
    worker_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    ip_address TEXT DEFAULT '0.0.0.0',
    details JSONB DEFAULT '{}',
    trace_id TEXT
);

CREATE TABLE IF NOT EXISTS credential_vault (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    sandbox_id TEXT NOT NULL,
    key_name TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, sandbox_id, key_name)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS sandbox_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_image TEXT NOT NULL,
    runtime TEXT DEFAULT 'python',
    vcpus REAL DEFAULT 1.0,
    memory_mb INTEGER DEFAULT 512,
    network_policy_id TEXT DEFAULT 'blocked',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_configs (
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by TEXT NOT NULL
);
"""


class DatabaseService:
    """Production database manager wrapping SQLite or PostgreSQL connection pool."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "thinkbox.db"

        # Determine backend engine
        dsn = settings.DATABASE_URL
        try:
            from thinkdome.core.kernel.kernel import Kernel
            kernel = Kernel.current()
            if kernel and kernel.initialized:
                db_url = kernel.config.get("db_url", "")
                if db_url:
                    dsn = db_url
        except Exception:
            pass

        self.is_postgres = dsn.startswith("postgres://") or dsn.startswith("postgresql://")
        if not self.is_postgres:
            if dsn.startswith("sqlite:///"):
                self.db_path = Path(dsn[10:])
            else:
                self.db_path = self.storage_dir / "thinkbox.db"
        else:
            self.db_path = self.storage_dir / "thinkbox.db"

        self._pool: Optional[asyncpg.Pool] = None
        self._loop_thread: Optional[AsyncLoopThread] = None

    async def initialize(self) -> None:
        """Initialize connection pool and declare schema (async startup)."""
        if self.is_postgres:
            logger.info("🐘 DatabaseService: Initializing PostgreSQL backend")
            try:
                # Start the background event loop thread
                self._loop_thread = AsyncLoopThread()
                self._loop_thread.start()

                # Wait for loop to be ready and initialize the asyncpg pool in that loop
                async def _create_pool():
                    return await asyncpg.create_pool(
                        dsn=self.settings.DATABASE_URL,
                        min_size=5,
                        max_size=20,
                        command_timeout=5,
                    )

                fut = asyncio.run_coroutine_threadsafe(
                    _create_pool(),
                    self._loop_thread.loop
                )
                # Do not let an unavailable database block application startup
                # indefinitely; fall back to SQLite after a bounded probe.
                self._pool = fut.result(timeout=5.0)

                # Execute schema setup
                await self._run_postgres_coro(self._setup_postgres_schema())
                logger.info("🐘 PostgreSQL backend connected and schema verified")
            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to connect to PostgreSQL ({e}). "
                    f"Falling back to local SQLite database."
                )
                self.is_postgres = False
                if self._loop_thread:
                    self._loop_thread.loop.call_soon_threadsafe(self._loop_thread.loop.stop)
                    self._loop_thread = None
                self._initialize_sqlite()
        else:
            logger.info(f"💾 DatabaseService: Initializing SQLite backend at {self.db_path}")
            self._initialize_sqlite()

    async def close(self) -> None:
        """Close connections gracefully."""
        if self._pool:
            fut = asyncio.run_coroutine_threadsafe(self._pool.close(), self._loop_thread.loop)
            fut.result()
        if self._loop_thread:
            self._loop_thread.loop.call_soon_threadsafe(self._loop_thread.loop.stop)
            self._loop_thread.join()

    # ── Database Driver Execution Engines ────────────────────────────────────────

    @property
    def effective_db_path(self) -> Path:
        try:
            from thinkdome.core.kernel.kernel import Kernel
            kernel = Kernel.current()
            if kernel and kernel.initialized:
                db_url = kernel.config.get("db_url", "")
                if db_url and db_url.startswith("sqlite:///"):
                    return Path(db_url[10:])
        except Exception:
            pass
        return self.db_path

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.effective_db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sqlite(self) -> None:
        with self._get_sqlite_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            for stmt in SQLITE_SCHEMA_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.commit()

    async def _setup_postgres_schema(self) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for stmt in POSTGRES_SCHEMA_SQL.strip().split(";"):
                    if stmt.strip():
                        await conn.execute(stmt)

                # ── Migrations: fix column types on existing tables ──
                # ALTER won't error if column is already TEXT thanks to the check.
                migrations = [
                    """
                    DO $$ BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='request_logs' AND column_name='request_payload' AND data_type='jsonb'
                        ) THEN
                            ALTER TABLE request_logs ALTER COLUMN request_payload TYPE TEXT USING request_payload::TEXT;
                            ALTER TABLE request_logs ALTER COLUMN response_payload TYPE TEXT USING response_payload::TEXT;
                        END IF;
                    END $$
                    """,
                ]
                for mig in migrations:
                    await conn.execute(mig.strip())

    async def _run_postgres_coro(self, coro) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop_thread.loop)
        return fut.result()

    # ── Sync SQL Query Wrapper APIs (Matches Original SQLite Signatures) ─────────

    def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a write query synchronously."""
        if self.is_postgres:
            pg_query, pg_params = self._convert_to_postgres(query, params)
            
            async def _execute():
                async with self._pool.acquire() as conn:
                    await conn.execute(pg_query, *pg_params)

            # Route to background thread loop
            fut = asyncio.run_coroutine_threadsafe(_execute(), self._loop_thread.loop)
            fut.result()
        else:
            with self._get_sqlite_conn() as conn:
                conn.execute(query, params)
                conn.commit()

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch a single row synchronously."""
        if self.is_postgres:
            pg_query, pg_params = self._convert_to_postgres(query, params)

            async def _fetch():
                async with self._pool.acquire() as conn:
                    row = await conn.fetchrow(pg_query, *pg_params)
                    return dict(row) if row else None

            fut = asyncio.run_coroutine_threadsafe(_fetch(), self._loop_thread.loop)
            return fut.result()
        else:
            with self._get_sqlite_conn() as conn:
                row = conn.execute(query, params).fetchone()
                return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all matching rows synchronously."""
        if self.is_postgres:
            pg_query, pg_params = self._convert_to_postgres(query, params)

            async def _fetch_all():
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(pg_query, *pg_params)
                    return [dict(row) for row in rows]

            fut = asyncio.run_coroutine_threadsafe(_fetch_all(), self._loop_thread.loop)
            return fut.result()
        else:
            with self._get_sqlite_conn() as conn:
                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]

    def _convert_to_postgres(self, query: str, params: tuple) -> tuple[str, list]:
        """Convert SQLite query syntax to PostgreSQL dialect.

        Handles:
          - '?' placeholders → '$1', '$2', ...
          - INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
          - TIMESTAMP DEFAULT CURRENT_TIMESTAMP → TIMESTAMPTZ DEFAULT NOW()
          - ISO datetime strings → datetime objects
        """
        import re

        # SQL dialect normalization
        q = query
        q = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', q, flags=re.IGNORECASE)
        q = re.sub(r'AUTOINCREMENT', '', q, flags=re.IGNORECASE)
        q = re.sub(r'TIMESTAMP\s+DEFAULT\s+CURRENT_TIMESTAMP', 'TIMESTAMPTZ DEFAULT NOW()', q, flags=re.IGNORECASE)

        # Placeholder conversion: ? → $1, $2, ...
        parts = q.split("?")
        new_query = []
        for i, part in enumerate(parts[:-1]):
            new_query.append(part)
            new_query.append(f"${i + 1}")
        new_query.append(parts[-1])

        # Parameter type coercion — only datetime strings need conversion.
        # JSON strings are passed through as-is; asyncpg handles JSONB text natively.
        new_params = []
        for p in params:
            if isinstance(p, str) and len(p) >= 10 and p[0].isdigit():
                # Check if it looks like an ISO format datetime (e.g. "2026-07-05T20:32:53.877590")
                if p[4:5] == '-' and p[7:8] == '-':
                    try:
                        dt = datetime.fromisoformat(p.replace(" ", "T"))
                        new_params.append(dt)
                        continue
                    except Exception:
                        pass
            new_params.append(p)

        return "".join(new_query), new_params

    # ── Database Operations ──────────────────────────────────────────────────────

    def log_audit(self, actor: str, action: str, ip_address: str, details: dict, trace_id: str = None) -> None:
        """Create an append-only audit event."""
        details_str = json.dumps(details)
        self.execute(
            "INSERT INTO audit_logs (actor, action, ip_address, details, trace_id) VALUES (?, ?, ?, ?, ?)",
            (actor, action, ip_address, details_str, trace_id),
        )

    def create_sandbox(
        self,
        sandbox_id: str,
        name: str,
        owner: str,
        memory_mb: int,
        cpu_cores: float,
        timeout_sec: int,
        network_enabled: bool,
        cost_per_hour: float,
        backend_type: str = "docker",
        gpu_count: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Insert or replace a sandbox registry record."""
        # Insert or replace logic using standard standard statements
        existing = self.get_sandbox(sandbox_id)
        if existing:
            self.execute(
                "UPDATE sandboxes SET name=?, owner=?, status='active', memory_mb=?, cpu_cores=?, gpu_count=?, timeout_sec=?, network_enabled=?, cost_per_hour=?, backend_type=? WHERE sandbox_id=?",
                (name, owner, memory_mb, cpu_cores, gpu_count, timeout_sec, bool(network_enabled), cost_per_hour, backend_type, sandbox_id)
            )
        else:
            self.execute(
                "INSERT INTO sandboxes (sandbox_id, name, owner, status, memory_mb, cpu_cores, gpu_count, timeout_sec, network_enabled, cost_per_hour, backend_type) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
                (sandbox_id, name, owner, memory_mb, cpu_cores, gpu_count, timeout_sec, bool(network_enabled), cost_per_hour, backend_type)
            )
        return self.get_sandbox(sandbox_id)

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single sandbox by ID using ThinkDome Sandbox ORM Model."""
        from thinkdome.apps.sandbox.models import Sandbox
        sb = Sandbox.query().filter(id=sandbox_id).first()
        if not sb:
            sb = Sandbox.query().filter(name=sandbox_id).first()
        if sb:
            d = sb.to_dict()
            d["sandbox_id"] = d.get("id")
            return d
        row = self.fetch_one("SELECT * FROM sandboxes WHERE sandbox_id = ?", (sandbox_id,))
        if row:
            row = dict(row)
            row["network_enabled"] = bool(row["network_enabled"])
        return row

    def list_sandboxes(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        """List active sandboxes using ThinkDome Sandbox ORM Model."""
        from thinkdome.apps.sandbox.models import Sandbox
        if owner:
            sbs = Sandbox.query().filter(owner=owner).all()
        else:
            sbs = Sandbox.query().all()

        if sbs:
            results = []
            for sb in sbs:
                d = sb.to_dict()
                d["sandbox_id"] = d.get("id")
                results.append(d)
            return results

        if owner:
            rows = self.fetch_all("SELECT * FROM sandboxes WHERE owner = ? ORDER BY created_at DESC", (owner,))
        else:
            rows = self.fetch_all("SELECT * FROM sandboxes ORDER BY created_at DESC")
        for r in rows:
            r["network_enabled"] = bool(r["network_enabled"])
        return rows

    def update_sandbox_status(self, sandbox_id: str, status: str) -> bool:
        """Update active status."""
        existing = self.get_sandbox(sandbox_id)
        if not existing:
            return False
        self.execute("UPDATE sandboxes SET status = ? WHERE sandbox_id = ?", (status, sandbox_id))
        return True

    def delete_sandbox(self, sandbox_id: str) -> bool:
        """Remove a sandbox record."""
        existing = self.get_sandbox(sandbox_id)
        if not existing:
            return False
        self.execute("DELETE FROM sandboxes WHERE sandbox_id = ?", (sandbox_id,))
        return True

    def health_check(self) -> dict:
        """Check status of the active engine connection."""
        if self.is_postgres:
            if not self._pool:
                return {"status": "unhealthy", "error": "PostgreSQL pool not ready"}
            try:
                # QuerySELECT 1 in background loop
                async def _ping():
                    async with self._pool.acquire() as conn:
                        return await conn.fetchval("SELECT 1")
                res = asyncio.run_coroutine_threadsafe(_ping(), self._loop_thread.loop).result()
                return {"status": "healthy", "engine": "postgresql", "ping": res}
            except Exception as e:
                return {"status": "unhealthy", "error": str(e)}
        else:
            try:
                with self._get_sqlite_conn() as conn:
                    conn.execute("SELECT 1")
                return {"status": "healthy", "engine": "sqlite"}
            except Exception as e:
                return {"status": "unhealthy", "error": str(e)}
