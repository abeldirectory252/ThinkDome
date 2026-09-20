"""Pydantic models for all structured Filebox data."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AccessLevel(str, Enum):
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"
    APPEND_ONLY = "append-only"
    SYSTEM_ONLY = "system-only"


class FileboxManifest(BaseModel):
    """Top-level ``filebox.yaml`` manifest."""

    version: str = "1.0"
    schema_version: int = 1
    agent_id: str = "default"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    filebox_root: str = ""
    capabilities: list[str] = Field(
        default_factory=lambda: [
            "memory",
            "skills",
            "projects",
            "knowledge",
            "audit",
        ]
    )


# ── Memory ──────────────────────────────────────────────────────────────────

class MemoryEntry(BaseModel):
    """A single memory record stored inside a topic Markdown file."""

    id: str
    topic: str = "core"
    title: str = ""
    content: str
    importance: str = "medium"  # low / medium / high / critical
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = ""
    archived: bool = False
    tags: list[str] = Field(default_factory=list)


class MemoryIndex(BaseModel):
    """Registry stored as ``memory/_index.json``."""

    version: int = 1
    entries: list[MemoryEntry] = Field(default_factory=list)


# ── Skills ──────────────────────────────────────────────────────────────────

class SkillMeta(BaseModel):
    """Frontmatter fields parsed from a ``SKILL.md`` file."""

    name: str
    version: str = "1.0"
    description: str = ""
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)


class SkillIndex(BaseModel):
    """Registry stored as ``skills/_index.json``."""

    version: int = 1
    skills: list[SkillMeta] = Field(default_factory=list)


# ── Projects ────────────────────────────────────────────────────────────────

class ProjectMeta(BaseModel):
    """Frontmatter from a ``PROJECT.md``."""

    name: str
    description: str = ""
    status: str = "active"  # active / paused / completed / archived
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)


# ── State ───────────────────────────────────────────────────────────────────

class SessionState(BaseModel):
    """Current session state at ``state/session.yaml``."""

    session_id: str = ""
    started_at: str = ""
    active_project: str = ""
    context_files: list[str] = Field(default_factory=list)


class TaskEntry(BaseModel):
    """A single task."""

    id: str
    title: str
    status: str = "pending"  # pending / in-progress / done / cancelled
    priority: str = "medium"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    project: str = ""
    description: str = ""


class TaskQueue(BaseModel):
    """Global task queue at ``state/tasks.yaml``."""

    version: int = 1
    tasks: list[TaskEntry] = Field(default_factory=list)


# ── Config ──────────────────────────────────────────────────────────────────

class PermissionRule(BaseModel):
    """A single permission entry in ``config/permissions.yaml``."""

    path: str
    access: AccessLevel = AccessLevel.READ_WRITE


class PermissionsConfig(BaseModel):
    """Full ``config/permissions.yaml``."""

    rules: list[PermissionRule] = Field(default_factory=list)
    defaults: dict[str, str] = Field(
        default_factory=lambda: {"access": "read-write"}
    )


# ── Audit ───────────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    """A single audit log entry (JSONL format)."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    action: str  # read / write / delete / append / move / copy
    path: str
    actor: str = "agent"
    reason: str = ""
    result: str = "ok"  # ok / denied / error
    details: dict[str, Any] = Field(default_factory=dict)


# ── File tree ───────────────────────────────────────────────────────────────

class FileNode(BaseModel):
    """A node in the Filebox file tree (used by browse API)."""

    name: str
    path: str
    is_dir: bool = False
    type: str = "file"  # "directory" or "file"
    size: int = 0
    modified: str = ""
    children: Optional[list["FileNode"]] = None
    mime_type: str = ""
    category: str = ""  # memory / skills / knowledge / workspace / state / config / identity / logs
