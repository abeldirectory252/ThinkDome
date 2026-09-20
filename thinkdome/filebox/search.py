"""Filebox search engine — SQLite FTS5 and full-text grep.

Provides fast indexed full-text search across all markdown, text, JSON, and
YAML files in a Filebox, with automatic fallback to streaming grep if the
FTS5 index is absent or stale.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml",
    ".py", ".sh", ".bash", ".js", ".ts", ".html", ".css",
    ".toml", ".ini", ".cfg", ".conf", ".sql", ".csv",
}


class FileboxSearch:
    """Indexed and grep search engine for a Filebox.

    Parameters
    ----------
    root:
        Root path of the Filebox.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        self._db_path = self._root / "config" / ".search_index.db"

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── FTS5 Indexing ────────────────────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
                path UNINDEXED,
                category UNINDEXED,
                title,
                content,
                tokenize = 'porter unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_files (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER
            )
            """
        )
        conn.commit()
        return conn

    def is_index_ready(self) -> bool:
        """Check whether the FTS5 database exists and has been built."""
        if not self._db_path.exists():
            return False
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cur = conn.execute("SELECT count(*) FROM indexed_files")
                count = cur.fetchone()[0]
                return count > 0
        except Exception:
            return False

    def build_index(self, force: bool = False) -> dict[str, Any]:
        """Build or incrementally update the SQLite FTS5 search index.

        Parameters
        ----------
        force:
            If True, drop and rebuild the index completely.
        """
        conn = self._get_connection()
        indexed_count = 0
        updated_count = 0
        deleted_count = 0

        try:
            if force:
                conn.execute("DELETE FROM fts_index")
                conn.execute("DELETE FROM indexed_files")
                conn.commit()

            # Read existing indexed file metadata
            cur = conn.execute("SELECT path, mtime, size FROM indexed_files")
            existing: dict[str, tuple[float, int]] = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

            current_files: set[str] = set()

            for path in self._root.rglob("*"):
                if path.is_dir():
                    continue
                # Skip the db file itself and log files
                if path == self._db_path or path.name.startswith("."):
                    continue

                rel_str = str(path.relative_to(self._root))
                # Skip search index db and tmp files
                if rel_str.startswith("config/.search_index.db"):
                    continue

                suffix = path.suffix.lower()
                if suffix not in TEXT_EXTENSIONS:
                    mime, _ = mimetypes.guess_type(path.name)
                    if not (mime and (mime.startswith("text/") or mime in ("application/json", "application/yaml"))):
                        continue

                current_files.add(rel_str)
                st = path.stat()
                mtime, size = st.st_mtime, st.st_size

                # Check if file has changed
                if rel_str in existing:
                    old_mtime, old_size = existing[rel_str]
                    if old_mtime == mtime and old_size == size:
                        continue
                    # Updated file: remove old fts row
                    conn.execute("DELETE FROM fts_index WHERE path = ?", (rel_str,))
                    updated_count += 1
                else:
                    indexed_count += 1

                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    logger.debug("Failed to read %s for search index: %s", path, exc)
                    continue

                category = rel_str.split(os.sep)[0] if os.sep in rel_str else ""
                title = path.stem.replace("-", " ").replace("_", " ").title()

                conn.execute(
                    "INSERT INTO fts_index(path, category, title, content) VALUES (?, ?, ?, ?)",
                    (rel_str, category, title, content),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_files(path, mtime, size) VALUES (?, ?, ?)",
                    (rel_str, mtime, size),
                )

            # Purge deleted files from index
            to_delete = set(existing.keys()) - current_files
            for del_path in to_delete:
                conn.execute("DELETE FROM fts_index WHERE path = ?", (del_path,))
                conn.execute("DELETE FROM indexed_files WHERE path = ?", (del_path,))
                deleted_count += 1

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('last_indexed_at', ?)", (now_iso,))
            conn.commit()

            return {
                "indexed": indexed_count,
                "updated": updated_count,
                "deleted": deleted_count,
                "total": len(current_files),
                "timestamp": now_iso,
            }
        finally:
            conn.close()

    def search_index(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search the FTS5 full-text index with relevance ranking and snippets."""
        if not self.is_index_ready():
            return []

        conn = self._get_connection()
        try:
            # Sanitize FTS query for boolean / token matching
            safe_query = self._sanitize_fts_query(query)
            if not safe_query:
                return []

            sql = """
                SELECT
                    path,
                    category,
                    title,
                    snippet(fts_index, 3, '<mark>', '</mark>', '...', 12) AS snippet,
                    bm25(fts_index) AS score
                FROM fts_index
                WHERE fts_index MATCH ?
                ORDER BY score ASC
                LIMIT ?
            """
            cur = conn.execute(sql, (safe_query, limit))
            results = []
            for row in cur.fetchall():
                results.append({
                    "path": row[0],
                    "category": row[1],
                    "title": row[2],
                    "snippet": row[3],
                    "score": round(float(row[4]), 4),
                })
            return results
        except sqlite3.OperationalError as e:
            logger.warning("FTS query failed: %s; falling back", e)
            return []
        finally:
            conn.close()

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Escape special characters for FTS5 syntax while preserving words."""
        words = [w.strip(" \"'*^:()[]{}-") for w in query.split() if w.strip(" \"'*^:()[]{}-")]
        if not words:
            return ""
        # Match each token with prefix search or exact match
        return " ".join(f'"{w}"*' for w in words)

    # ── Fallback Grep Search ──────────────────────────────────────────────────

    def grep(self, query: str, path: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Streaming text search across readable files without requiring an index."""
        target = (self._root / path.lstrip("/")).resolve()
        if not str(target).startswith(str(self._root)):
            raise PermissionError("Path escapes Filebox root")
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        results: list[dict[str, Any]] = []
        query_lower = query.lower()

        search_dirs = [target] if target.is_dir() else [target.parent]
        iterator = target.rglob("*") if target.is_dir() else [target]

        for fpath in iterator:
            if fpath.is_dir():
                continue
            suffix = fpath.suffix.lower()
            if suffix not in TEXT_EXTENSIONS:
                mime, _ = mimetypes.guess_type(fpath.name)
                if not (mime and (mime.startswith("text/") or mime in ("application/json", "application/yaml"))):
                    continue

            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if query_lower in text.lower():
                rel = str(fpath.relative_to(self._root))
                category = rel.split(os.sep)[0] if os.sep in rel else ""
                matches = []
                for i, line in enumerate(text.splitlines(), 1):
                    if query_lower in line.lower():
                        matches.append({"line": i, "text": line.strip()[:240]})
                        if len(matches) >= 5:
                            break

                results.append({
                    "path": rel,
                    "category": category,
                    "title": fpath.stem.replace("-", " ").replace("_", " ").title(),
                    "matches": matches,
                })
                if len(results) >= limit:
                    break

        return results

    def search(self, query: str, path: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Unified search: Uses FTS5 index if available for root searches, else grep."""
        if not path and self.is_index_ready():
            fts_results = self.search_index(query, limit=limit)
            if fts_results:
                return fts_results
        return self.grep(query, path=path, limit=limit)
