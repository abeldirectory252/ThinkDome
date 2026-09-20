"""Project lifecycle management for the Filebox.

Projects live under ``workspace/projects/`` with a standardised layout:
  - PROJECT.md (YAML frontmatter + description)
  - context.md, tasks.md, decisions.md
  - src/, docs/, notes/
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

import yaml

from thinkdome.filebox.core import Filebox
from thinkdome.filebox.schemas import ProjectMeta


class FileboxProjects:
    """Manage workspace projects inside the Filebox."""

    PROJECTS_ROOT = "workspace/projects"

    def __init__(self, filebox: Filebox):
        self._fb = filebox

    # ── CRUD ────────────────────────────────────────────────────────────

    def list_projects(self) -> list[ProjectMeta]:
        """Enumerate all projects and their metadata."""
        projects: list[ProjectMeta] = []
        root = f"{self.PROJECTS_ROOT}"
        if not self._fb.exists(root):
            return projects
        for item in self._fb.list(root):
            if item["is_dir"]:
                pm_path = f"{item['path']}/PROJECT.md"
                if self._fb.exists(pm_path):
                    content = self._fb.read_text(pm_path)
                    projects.append(self._parse_project(content, item["name"]))
                else:
                    projects.append(ProjectMeta(name=item["name"]))
        return projects

    def create_project(
        self,
        name: str,
        description: str = "",
        *,
        tags: list[str] | None = None,
    ) -> ProjectMeta:
        """Scaffold a new project directory with standard files."""
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name.lower())
        base = f"{self.PROJECTS_ROOT}/{safe_name}"
        if self._fb.exists(base):
            raise FileExistsError(f"Project already exists: {safe_name}")

        now = datetime.now(timezone.utc).isoformat()
        meta = ProjectMeta(
            name=safe_name,
            description=description,
            status="active",
            created_at=now,
            tags=tags or [],
        )

        # Create directory structure.
        for sub in ("src", "docs", "notes"):
            self._fb.mkdir(f"{base}/{sub}", reason=f"Scaffold project: {safe_name}")

        # Write PROJECT.md.
        frontmatter = yaml.dump(meta.model_dump(), default_flow_style=False)
        project_md = (
            f"---\n{frontmatter}---\n\n"
            f"# {name}\n\n"
            f"## Goal\n{description or 'TBD'}\n\n"
            f"## Context\nKey background information.\n\n"
            f"## Current State\nProject just created.\n\n"
            f"## Instructions\nProject-specific instructions.\n"
        )
        self._fb.write(f"{base}/PROJECT.md", project_md, reason=f"Create project: {safe_name}")
        self._fb.write(f"{base}/context.md", f"# {name} — Context\n\n", reason="Init context")
        self._fb.write(f"{base}/tasks.md", f"# {name} — Tasks\n\n- [ ] Initial setup\n", reason="Init tasks")
        self._fb.write(f"{base}/decisions.md", f"# {name} — Decisions\n\n", reason="Init decisions")

        return meta

    def open_project(self, name: str) -> Optional[ProjectMeta]:
        """Load the project metadata from PROJECT.md."""
        path = f"{self.PROJECTS_ROOT}/{name}/PROJECT.md"
        if not self._fb.exists(path):
            return None
        content = self._fb.read_text(path)
        return self._parse_project(content, name)

    def read_project_md(self, name: str) -> Optional[str]:
        """Load the raw PROJECT.md content."""
        path = f"{self.PROJECTS_ROOT}/{name}/PROJECT.md"
        if not self._fb.exists(path):
            return None
        return self._fb.read_text(path)

    def get_project_context(self, name: str) -> dict:
        """Load project metadata, context, tasks, and decisions."""
        base = f"{self.PROJECTS_ROOT}/{name}"
        result = {"name": name, "exists": self._fb.exists(base)}
        if not result["exists"]:
            return result
        for fname in ("PROJECT.md", "context.md", "tasks.md", "decisions.md"):
            path = f"{base}/{fname}"
            key = fname.replace(".md", "").replace(".", "_").lower()
            result[key] = self._fb.read_text(path) if self._fb.exists(path) else ""
        result["meta"] = self._parse_project(result.get("project", ""), name).model_dump()
        return result

    def archive_project(self, name: str) -> bool:
        """Move a project to archived status."""
        base = f"{self.PROJECTS_ROOT}/{name}"
        if not self._fb.exists(base):
            return False
        pm_path = f"{base}/PROJECT.md"
        if self._fb.exists(pm_path):
            content = self._fb.read_text(pm_path)
            content = re.sub(
                r"status:\s*\w+", "status: archived", content, count=1
            )
            self._fb.write(pm_path, content, reason=f"Archive project: {name}")
        return True

    def delete_project(self, name: str) -> bool:
        """Permanently remove a project directory."""
        base = f"{self.PROJECTS_ROOT}/{name}"
        return self._fb.delete(base, reason=f"Delete project: {name}")

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_project(content: str, fallback_name: str) -> ProjectMeta:
        """Extract project metadata from PROJECT.md frontmatter."""
        match = re.match(r"^---\s*\n(.*?\n)---\s*\n", content, re.DOTALL)
        if match:
            try:
                data = yaml.safe_load(match.group(1)) or {}
                return ProjectMeta(
                    name=data.get("name", fallback_name),
                    description=data.get("description", ""),
                    status=data.get("status", "active"),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    tags=data.get("tags", []),
                )
            except yaml.YAMLError:
                pass
        return ProjectMeta(name=fallback_name)
