"""Semantic memory API for the Filebox.

Memories are stored as Markdown entries inside topic files under
``memory/`` with a central ``_index.json`` registry for fast look-up.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from thinkdome.filebox.core import Filebox
from thinkdome.filebox.schemas import MemoryEntry, MemoryIndex


class FileboxMemory:
    """High-level memory operations backed by the Filebox filesystem."""

    def __init__(self, filebox: Filebox):
        self._fb = filebox

    # ── Index management ────────────────────────────────────────────────

    def _load_index(self) -> MemoryIndex:
        try:
            raw = self._fb.read_text("memory/_index.json")
            return MemoryIndex(**json.loads(raw))
        except (FileNotFoundError, json.JSONDecodeError):
            return MemoryIndex()

    def _save_index(self, index: MemoryIndex) -> None:
        self._fb.write(
            "memory/_index.json",
            index.model_dump_json(indent=2),
            system=True,
            reason="Update memory index",
        )

    # ── CRUD ────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        *,
        topic: str = "core",
        title: str = "",
        importance: str = "medium",
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """Add a new memory entry."""
        entry = MemoryEntry(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            topic=topic,
            title=title or (content.strip().splitlines()[0][:60] if content else "Memory"),
            content=content,
            importance=importance,
            tags=tags or [],
        )
        # Append to topic file.
        md_path = f"memory/{topic}.md"
        md_block = self._render_entry(entry)
        if self._fb.exists(md_path):
            self._fb.append(md_path, f"\n{md_block}", reason="New memory entry")
        else:
            header = f"# Memory: {topic.title()}\n\n"
            self._fb.write(md_path, header + md_block, reason="Create memory topic file")
        # Update index.
        index = self._load_index()
        index.entries.append(entry)
        self._save_index(index)
        return entry

    def recall(self, query: str = "", *, limit: int = 20) -> list[MemoryEntry]:
        """Search memories by keyword. If query is empty, return all non-archived memories."""
        index = self._load_index()
        query_lower = query.lower().strip()
        matches = []
        for entry in index.entries:
            if entry.archived:
                continue
            if (
                not query_lower
                or query_lower in entry.content.lower()
                or query_lower in entry.topic.lower()
                or query_lower in getattr(entry, "title", "").lower()
                or any(query_lower in t.lower() for t in entry.tags)
            ):
                matches.append(entry)
                if len(matches) >= limit:
                    break
        return matches

    def update(self, entry_id: str, new_content: str) -> Optional[MemoryEntry]:
        """Update the content of an existing memory entry."""
        index = self._load_index()
        for entry in index.entries:
            if entry.id == entry_id:
                entry.content = new_content
                entry.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_index(index)
                self._rebuild_topic(entry.topic, index)
                return entry
        return None

    def forget(self, entry_id: str) -> bool:
        """Mark a memory entry as archived (soft-delete)."""
        index = self._load_index()
        for entry in index.entries:
            if entry.id == entry_id:
                entry.archived = True
                entry.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_index(index)
                self._rebuild_topic(entry.topic, index)
                return True
        return False

    def archive(self, entry_id: str) -> bool:
        """Move a memory to the archive folder."""
        return self.forget(entry_id)  # Same semantics for now.

    def list_topics(self) -> list[str]:
        """Return all memory topic names."""
        topics = set()
        for entry in self._load_index().entries:
            if not entry.archived:
                topics.add(entry.topic)
        return sorted(topics)

    def all(self, *, include_archived: bool = False) -> list[MemoryEntry]:
        """Return all memory entries."""
        index = self._load_index()
        if include_archived:
            return index.entries
        return [e for e in index.entries if not e.archived]

    def consolidate(self) -> int:
        """Remove duplicate or archived entries from topic files.

        Returns the number of cleaned-up entries.
        """
        index = self._load_index()
        removed = 0
        active = [e for e in index.entries if not e.archived]
        archived = [e for e in index.entries if e.archived]
        removed = len(archived)
        # Keep only active entries in the index.
        index.entries = active
        self._save_index(index)
        # Rebuild all topic files.
        topics = {e.topic for e in active}
        for topic in topics:
            self._rebuild_topic(topic, index)
        return removed

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _render_entry(entry: MemoryEntry) -> str:
        """Render a memory entry as a Markdown block."""
        date = entry.created_at[:10] if entry.created_at else "unknown"
        tags = f" | tags: {', '.join(entry.tags)}" if entry.tags else ""
        return (
            f"## [{date}] {entry.content[:80]}\n"
            f"<!-- id: {entry.id} | importance: {entry.importance} "
            f"| created: {entry.created_at}{tags} -->\n\n"
            f"{entry.content}\n\n---\n"
        )

    def _rebuild_topic(self, topic: str, index: MemoryIndex) -> None:
        """Re-write the topic file from the index (active entries only)."""
        entries = [e for e in index.entries if e.topic == topic and not e.archived]
        if not entries:
            return
        content = f"# Memory: {topic.title()}\n\n"
        for entry in entries:
            content += self._render_entry(entry) + "\n"
        self._fb.write(
            f"memory/{topic}.md", content, reason="Rebuild memory topic file"
        )
