"""Skill discovery and loading for the Filebox.

Skills are directories under ``skills/`` each containing a ``SKILL.md``
file with YAML frontmatter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml

from thinkdome.filebox.core import Filebox
from thinkdome.filebox.schemas import SkillIndex, SkillMeta


class FileboxSkills:
    """Manage agent skills stored in the Filebox."""

    def __init__(self, filebox: Filebox):
        self._fb = filebox

    # ── Index ───────────────────────────────────────────────────────────

    def _load_index(self) -> SkillIndex:
        try:
            raw = self._fb.read_text("skills/_index.json")
            return SkillIndex(**json.loads(raw))
        except (FileNotFoundError, json.JSONDecodeError):
            return SkillIndex()

    def _save_index(self, index: SkillIndex) -> None:
        self._fb.write(
            "skills/_index.json",
            index.model_dump_json(indent=2),
            system=True,
            reason="Update skill index",
        )

    def _rebuild_index(self) -> SkillIndex:
        """Scan the skills directory and rebuild the index from SKILL.md files."""
        skills_dir = self._fb._resolve("skills")
        skills: list[SkillMeta] = []
        if skills_dir.exists():
            for child in sorted(skills_dir.iterdir()):
                if child.is_dir():
                    skill_md = child / "SKILL.md"
                    if skill_md.exists():
                        meta = self._parse_frontmatter(
                            skill_md.read_text(encoding="utf-8"),
                            child.name,
                        )
                        skills.append(meta)
        index = SkillIndex(skills=skills)
        self._save_index(index)
        return index

    # ── CRUD ────────────────────────────────────────────────────────────

    def list_skills(self) -> list[SkillMeta]:
        """Return skill summaries."""
        index = self._load_index()
        if not index.skills:
            index = self._rebuild_index()
        return index.skills

    def load_skill(self, name: str) -> Optional[str]:
        """Read and return the full SKILL.md content."""
        path = f"skills/{name}/SKILL.md"
        if not self._fb.exists(path):
            return None
        return self._fb.read_text(path)

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """Fetch metadata for a specific skill."""
        index = self._load_index()
        for s in index.skills:
            if s.name == name:
                return s
        return None

    def create_skill(
        self,
        name: str,
        content: str = "",
        *,
        description: str = "",
        instructions: str = "",
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
    ) -> SkillMeta:
        """Create a new skill directory with SKILL.md."""
        body = content or instructions
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        dir_path = f"skills/{safe_name}"
        self._fb.mkdir(dir_path, reason=f"Create skill: {safe_name}")
        # Write SKILL.md with frontmatter.
        frontmatter = yaml.dump(
            {
                "name": safe_name,
                "version": "1.0",
                "description": description,
                "enabled": True,
                "tags": tags or [],
                "triggers": triggers or [],
            },
            default_flow_style=False,
        )
        full_content = f"---\n{frontmatter}---\n\n{body}"
        self._fb.write(
            f"{dir_path}/SKILL.md", full_content, reason=f"Create skill: {safe_name}"
        )
        # Create standard subdirectories.
        for sub in ("examples", "resources"):
            self._fb.mkdir(f"{dir_path}/{sub}", reason=f"Create {sub} for skill")
        # Rebuild index.
        index = self._rebuild_index()
        return next((s for s in index.skills if s.name == safe_name), SkillMeta(name=safe_name))

    def update_skill(self, name: str, content: str) -> bool:
        """Update the SKILL.md content of an existing skill."""
        path = f"skills/{name}/SKILL.md"
        if not self._fb.exists(path):
            return False
        self._fb.write(path, content, reason=f"Update skill: {name}")
        self._rebuild_index()
        return True

    def disable_skill(self, name: str) -> bool:
        """Mark a skill as disabled in its frontmatter."""
        path = f"skills/{name}/SKILL.md"
        if not self._fb.exists(path):
            return False
        content = self._fb.read_text(path)
        # Toggle enabled in frontmatter.
        content = re.sub(
            r"enabled:\s*true", "enabled: false", content, flags=re.IGNORECASE
        )
        self._fb.write(path, content, reason=f"Disable skill: {name}")
        self._rebuild_index()
        return True

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str, fallback_name: str) -> SkillMeta:
        """Extract YAML frontmatter from a SKILL.md file."""
        match = re.match(r"^---\s*\n(.*?\n)---\s*\n", content, re.DOTALL)
        if match:
            try:
                data = yaml.safe_load(match.group(1)) or {}
                return SkillMeta(
                    name=data.get("name", fallback_name),
                    version=str(data.get("version", "1.0")),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                    tags=data.get("tags", []),
                    triggers=data.get("triggers", []),
                )
            except yaml.YAMLError:
                pass
        return SkillMeta(name=fallback_name)
