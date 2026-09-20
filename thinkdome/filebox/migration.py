"""Filebox Migration Engine.

Migrates legacy Filebox directory layouts and encrypted storage containers
into the modern, production-grade Filebox architecture.

Supported migration paths:
1. Legacy sandbox filesystem (e.g. ``/sandbox/`` with flat ``memory.md``,
   unstructured skills, and projects) -> Standardized Filebox layout.
2. Legacy ThinkDome platform storage (``<storage>/filebox/<tenant>/<owner>/``
   with ``.box`` encrypted containers or old folder structures) -> Modern
   isolated Filebox data tree (``<storage>/filebox_data/<tenant>/<owner>/``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from thinkdome.core.config import get_settings, get_workspace_root
from thinkdome.filebox import bootstrap
from thinkdome.filebox.core import Filebox
from thinkdome.filebox.schemas import (
    FileboxManifest,
    MemoryEntry,
    MemoryIndex,
    SkillIndex,
    SkillMeta,
)

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """Summary of a completed or dry-run migration."""
    source: str
    target: str
    dry_run: bool
    status: str = "success"  # success, partial, failed
    files_copied: list[str] = field(default_factory=list)
    files_transformed: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "dry_run": self.dry_run,
            "status": self.status,
            "total_copied": len(self.files_copied),
            "total_transformed": len(self.files_transformed),
            "total_skipped": len(self.files_skipped),
            "files_copied": self.files_copied,
            "files_transformed": self.files_transformed,
            "files_skipped": self.files_skipped,
            "warnings": self.warnings,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }


class FileboxMigrator:
    """Migrate legacy Filebox data to standard Filebox directory tree."""

    # ── Migration from arbitrary directory ──────────────────────────────────

    def migrate_directory(
        self,
        source_dir: str | Path,
        target_dir: str | Path,
        *,
        agent_id: str = "migrated-agent",
        dry_run: bool = False,
        backup: bool = True,
    ) -> MigrationReport:
        """Migrate an existing directory (e.g. /sandbox or an old filebox)
        into the standardized Filebox layout.
        """
        src = Path(source_dir).resolve()
        dst = Path(target_dir).resolve()
        report = MigrationReport(source=str(src), target=str(dst), dry_run=dry_run)

        if not src.exists() or not src.is_dir():
            report.status = "failed"
            report.errors.append(f"Source directory does not exist: {src}")
            return report

        if dst == src:
            report.status = "failed"
            report.errors.append("Target directory cannot be identical to source directory.")
            return report

        # Optional backup before mutating target if target already exists
        if backup and dst.exists() and not dry_run:
            backup_path = dst.parent / f"{dst.name}.backup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            try:
                shutil.copytree(str(dst), str(backup_path))
                report.warnings.append(f"Created backup of existing target at {backup_path}")
            except Exception as e:
                report.warnings.append(f"Could not create backup of target: {e}")

        if not dry_run:
            # Bootstrap standard skeleton and default config in target
            bootstrap.init(dst, agent_id=agent_id, force=False)

        # 1. Migrate Memory
        self._migrate_memory(src, dst, report, dry_run=dry_run)

        # 2. Migrate Skills
        self._migrate_skills(src, dst, report, dry_run=dry_run)

        # 3. Migrate Knowledge
        self._migrate_knowledge(src, dst, report, dry_run=dry_run)

        # 4. Migrate Workspace
        self._migrate_workspace(src, dst, report, dry_run=dry_run)

        # 5. Migrate State & Config
        self._migrate_state_and_config(src, dst, report, dry_run=dry_run)

        # 6. Migrate Logs & History
        self._migrate_logs(src, dst, report, dry_run=dry_run)

        # 7. Migrate remaining unclassified files to workspace/drafts
        self._migrate_unclassified(src, dst, report, dry_run=dry_run)

        if report.errors:
            report.status = "partial" if report.files_copied or report.files_transformed else "failed"

        return report

    def _migrate_memory(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        src_mem = src / "memory"
        dst_mem = dst / "memory"

        # Case 1: Legacy memory.md at root or inside memory/
        legacy_memory_files = [src / "memory.md", src_mem / "memory.md"]
        for mem_file in legacy_memory_files:
            if mem_file.exists() and mem_file.is_file():
                try:
                    text = mem_file.read_text(encoding="utf-8", errors="replace")
                    if not dry_run:
                        # Append content into memory/core.md
                        core_file = dst_mem / "core.md"
                        existing = core_file.read_text(encoding="utf-8", errors="replace") if core_file.exists() else ""
                        new_content = existing.rstrip() + "\n\n" + f"<!-- Migrated from {mem_file.name} -->\n" + text.strip() + "\n"
                        core_file.write_text(new_content, encoding="utf-8")
                        self._rebuild_memory_index(dst)
                    report.files_transformed.append(f"{mem_file.relative_to(src)} -> memory/core.md")
                except Exception as exc:
                    report.errors.append(f"Failed to migrate {mem_file}: {exc}")

        # Case 2: Legacy context.md
        legacy_context_files = [src / "context.md", src_mem / "context.md"]
        for ctx_file in legacy_context_files:
            if ctx_file.exists() and ctx_file.is_file():
                try:
                    text = ctx_file.read_text(encoding="utf-8", errors="replace")
                    if not dry_run:
                        pref_file = dst_mem / "preferences.md"
                        existing = pref_file.read_text(encoding="utf-8", errors="replace") if pref_file.exists() else ""
                        new_content = existing.rstrip() + "\n\n" + f"<!-- Migrated from {ctx_file.name} -->\n" + text.strip() + "\n"
                        pref_file.write_text(new_content, encoding="utf-8")
                        self._rebuild_memory_index(dst)
                    report.files_transformed.append(f"{ctx_file.relative_to(src)} -> memory/preferences.md")
                except Exception as exc:
                    report.errors.append(f"Failed to migrate {ctx_file}: {exc}")

        # Case 3: Any existing topic markdown files in memory/
        if src_mem.exists() and src_mem.is_dir():
            for item in src_mem.iterdir():
                if item.is_file() and item.suffix.lower() == ".md" and item.name not in ("memory.md", "context.md"):
                    target_file = dst_mem / item.name
                    try:
                        if not dry_run:
                            if target_file.exists():
                                existing = target_file.read_text(encoding="utf-8", errors="replace")
                                item_text = item.read_text(encoding="utf-8", errors="replace")
                                target_file.write_text(existing.rstrip() + "\n\n" + item_text.strip() + "\n", encoding="utf-8")
                            else:
                                shutil.copy2(str(item), str(target_file))
                            self._rebuild_memory_index(dst)
                        report.files_copied.append(f"{item.relative_to(src)} -> memory/{item.name}")
                    except Exception as exc:
                        report.errors.append(f"Failed to copy memory file {item}: {exc}")

            # Subdirectory: history/ -> memory/archive/
            hist_dir = src_mem / "history"
            if hist_dir.exists() and hist_dir.is_dir():
                for hfile in hist_dir.rglob("*"):
                    if hfile.is_file():
                        rel = hfile.relative_to(hist_dir)
                        target_hfile = dst_mem / "archive" / rel
                        try:
                            if not dry_run:
                                target_hfile.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(str(hfile), str(target_hfile))
                            report.files_copied.append(f"{hfile.relative_to(src)} -> memory/archive/{rel}")
                        except Exception as exc:
                            report.errors.append(f"Failed to copy archive file {hfile}: {exc}")

    def _migrate_skills(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        src_skills = src / "skills"
        dst_skills = dst / "skills"

        # Case 1: Root skill.md in skills/ or project root
        root_skill = src_skills / "skill.md" if src_skills.exists() else None
        if not root_skill or not root_skill.exists():
            root_skill = src / "skill.md" if (src / "skill.md").exists() else None

        if root_skill and root_skill.exists() and root_skill.is_file():
            target_general = dst_skills / "general" / "SKILL.md"
            try:
                if not dry_run:
                    content = root_skill.read_text(encoding="utf-8", errors="replace")
                    content_with_frontmatter = self._ensure_skill_frontmatter("general", content)
                    target_general.parent.mkdir(parents=True, exist_ok=True)
                    target_general.write_text(content_with_frontmatter, encoding="utf-8")
                    self._rebuild_skills_index(dst)
                report.files_transformed.append(f"{root_skill.relative_to(src)} -> skills/general/SKILL.md")
            except Exception as exc:
                report.errors.append(f"Failed to migrate root skill {root_skill}: {exc}")

        # Case 2: Subdirectories under skills/
        if src_skills.exists() and src_skills.is_dir():
            for skill_dir in src_skills.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_name = skill_dir.name.lower().replace(" ", "-")
                target_skill_dir = dst_skills / skill_name

                # Look for skill.md or SKILL.md
                candidate_files = [skill_dir / "SKILL.md", skill_dir / "skill.md", skill_dir / f"{skill_name}.md"]
                found_md = next((f for f in candidate_files if f.exists() and f.is_file()), None)

                if found_md:
                    try:
                        if not dry_run:
                            target_skill_dir.mkdir(parents=True, exist_ok=True)
                            content = found_md.read_text(encoding="utf-8", errors="replace")
                            content = self._ensure_skill_frontmatter(skill_name, content)
                            (target_skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
                        report.files_transformed.append(f"{found_md.relative_to(src)} -> skills/{skill_name}/SKILL.md")
                    except Exception as exc:
                        report.errors.append(f"Failed to migrate skill {found_md}: {exc}")

                # Copy additional skill resources / examples
                for extra in skill_dir.iterdir():
                    if extra == found_md or extra.name in ("SKILL.md", "skill.md"):
                        continue
                    target_extra = target_skill_dir / extra.name
                    try:
                        if not dry_run:
                            target_skill_dir.mkdir(parents=True, exist_ok=True)
                            if extra.is_dir():
                                shutil.copytree(str(extra), str(target_extra), dirs_exist_ok=True)
                            else:
                                shutil.copy2(str(extra), str(target_extra))
                        report.files_copied.append(f"{extra.relative_to(src)} -> skills/{skill_name}/{extra.name}")
                    except Exception as exc:
                        report.errors.append(f"Failed to copy skill asset {extra}: {exc}")

            if not dry_run:
                self._rebuild_skills_index(dst)

    def _ensure_skill_frontmatter(self, skill_name: str, content: str) -> str:
        """Add YAML frontmatter if missing."""
        if content.strip().startswith("---"):
            return content
        frontmatter = f"""---
name: {skill_name}
version: "1.0"
description: Migrated {skill_name} skill
enabled: true
tags: [{skill_name}]
triggers: [{skill_name}]
---

"""
        return frontmatter + content

    def _migrate_knowledge(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        src_k = src / "knowledge"
        dst_k = dst / "knowledge"
        if not src_k.exists() or not src_k.is_dir():
            return

        for item in src_k.rglob("*"):
            if item.is_file() and item.name != "_index.json":
                rel = item.relative_to(src_k)
                # Map into notes or documents if currently flat
                if len(rel.parts) == 1:
                    target_path = dst_k / "notes" / rel.name
                else:
                    target_path = dst_k / rel
                try:
                    if not dry_run:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(target_path))
                    report.files_copied.append(f"{item.relative_to(src)} -> knowledge/{target_path.relative_to(dst_k)}")
                except Exception as exc:
                    report.errors.append(f"Failed to migrate knowledge file {item}: {exc}")

    def _migrate_workspace(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        src_ws = src / "workspace"
        dst_ws = dst / "workspace"
        if not src_ws.exists() or not src_ws.is_dir():
            return

        for item in src_ws.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src_ws)
                # Check top-level folder
                top = rel.parts[0] if rel.parts else ""
                if top in ("projects", "drafts", "scratch"):
                    target_path = dst_ws / rel
                else:
                    target_path = dst_ws / "drafts" / rel

                try:
                    if not dry_run:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(target_path))
                    report.files_copied.append(f"{item.relative_to(src)} -> workspace/{target_path.relative_to(dst_ws)}")
                except Exception as exc:
                    report.errors.append(f"Failed to migrate workspace file {item}: {exc}")

    def _migrate_state_and_config(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        for folder in ("state", "config"):
            src_dir = src / folder
            dst_dir = dst / folder
            if not src_dir.exists() or not src_dir.is_dir():
                continue
            for item in src_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(src_dir)
                    target_path = dst_dir / rel
                    try:
                        if not dry_run:
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(item), str(target_path))
                        report.files_copied.append(f"{item.relative_to(src)} -> {folder}/{rel}")
                    except Exception as exc:
                        report.errors.append(f"Failed to migrate {folder} file {item}: {exc}")

    def _migrate_logs(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        src_logs = src / "logs"
        dst_logs = dst / "logs"
        if not src_logs.exists() or not src_logs.is_dir():
            return
        for item in src_logs.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src_logs)
                target_path = dst_logs / rel
                try:
                    if not dry_run:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(target_path))
                    report.files_copied.append(f"{item.relative_to(src)} -> logs/{rel}")
                except Exception as exc:
                    report.errors.append(f"Failed to migrate log file {item}: {exc}")

    def _migrate_unclassified(
        self, src: Path, dst: Path, report: MigrationReport, dry_run: bool = False
    ) -> None:
        """Check for unclassified files at the root of src."""
        known_roots = {
            "memory", "skills", "knowledge", "workspace",
            "state", "config", "logs", "identity",
            "memory.md", "context.md", "skill.md", "filebox.yaml",
        }
        for item in src.iterdir():
            if item.name.startswith(".") or item.name in known_roots:
                continue
            # Put unclassified file into workspace/drafts/
            target_path = dst / "workspace" / "drafts" / item.name
            try:
                if not dry_run:
                    if item.is_dir():
                        shutil.copytree(str(item), str(target_path), dirs_exist_ok=True)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(target_path))
                report.files_copied.append(f"{item.name} -> workspace/drafts/{item.name}")
            except Exception as exc:
                report.errors.append(f"Failed to copy unclassified item {item}: {exc}")

    # ── Index rebuilders ────────────────────────────────────────────────────

    def _rebuild_memory_index(self, dst: Path) -> None:
        dst_mem = dst / "memory"
        if not dst_mem.exists():
            return
        entries: list[MemoryEntry] = []
        for mf in dst_mem.glob("*.md"):
            topic = mf.stem
            try:
                content = mf.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            sections = re.split(r"^##\s+", content, flags=re.MULTILINE)
            for sec in sections[1:]:
                lines = sec.strip().splitlines()
                title = lines[0].strip() if lines else "Untitled"
                body = "\n".join(lines[1:]).strip() if len(lines) > 1 else title
                entries.append(
                    MemoryEntry(
                        id=f"migrated-{len(entries) + 1}",
                        topic=topic,
                        title=title,
                        content=body or title,
                        importance="medium",
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                )

        idx = MemoryIndex(entries=entries)
        (dst_mem / "_index.json").write_text(idx.model_dump_json(indent=2), encoding="utf-8")

    def _rebuild_skills_index(self, dst: Path) -> None:
        dst_skills = dst / "skills"
        if not dst_skills.exists():
            return
        skills_list = []
        for skill_dir in dst_skills.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
                m = re.match(r"^---\s*\n(.*?)\n---", content, flags=re.DOTALL)
                if m:
                    meta_dict = yaml.safe_load(m.group(1)) or {}
                    skills_list.append(
                        SkillMeta(
                            name=meta_dict.get("name", skill_dir.name),
                            version=str(meta_dict.get("version", "1.0")),
                            description=meta_dict.get("description", ""),
                            enabled=bool(meta_dict.get("enabled", True)),
                            tags=meta_dict.get("tags", []),
                            triggers=meta_dict.get("triggers", []),
                            path=f"skills/{skill_dir.name}/SKILL.md",
                        )
                    )
            except Exception as e:
                logger.warning("Could not parse skill %s: %s", skill_md, e)

        idx = SkillIndex(skills=skills_list)
        (dst_skills / "_index.json").write_text(idx.model_dump_json(indent=2), encoding="utf-8")

    # ── Migration from Legacy Platform Storage ──────────────────────────────

    def migrate_legacy_storage(
        self,
        *,
        tenant_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> list[MigrationReport]:
        """Migrate all or specific legacy FileBox tenant/owner volumes from
        ``<storage>/filebox/<tenant>/<owner>`` into ``<storage>/filebox_data/<tenant>/<owner>``.
        """
        settings = get_settings()
        storage_dir = Path(settings.FILE_STORAGE_DIR)
        if not storage_dir.is_absolute():
            storage_dir = get_workspace_root() / storage_dir

        legacy_root = storage_dir / "filebox"
        reports: list[MigrationReport] = []

        if not legacy_root.exists():
            return reports

        # Find tenant directories
        tenants = [legacy_root / tenant_id] if tenant_id else [t for t in legacy_root.iterdir() if t.is_dir()]

        for tenant_dir in tenants:
            if not tenant_dir.exists() or not tenant_dir.is_dir():
                continue
            cur_tenant = tenant_dir.name

            owners = [tenant_dir / owner_id] if owner_id else [o for o in tenant_dir.iterdir() if o.is_dir()]
            for owner_dir in owners:
                if not owner_dir.exists() or not owner_dir.is_dir():
                    continue
                cur_owner = owner_dir.name
                target_root = storage_dir / "filebox_data" / cur_tenant / cur_owner

                report = self._migrate_owner_volume(
                    owner_dir=owner_dir,
                    target_root=target_root,
                    tenant_id=cur_tenant,
                    owner_id=cur_owner,
                    dry_run=dry_run,
                )
                reports.append(report)

        return reports

    def _migrate_owner_volume(
        self,
        owner_dir: Path,
        target_root: Path,
        tenant_id: str,
        owner_id: str,
        dry_run: bool = False,
    ) -> MigrationReport:
        report = MigrationReport(source=str(owner_dir), target=str(target_root), dry_run=dry_run)

        if not dry_run:
            bootstrap.init(target_root, agent_id=owner_id)

        # Look for encrypted BoxContainer (.box file)
        from thinkdome.platform.storage.filebox.container import BoxContainer
        box_files = list(owner_dir.glob("*.box"))

        for box_file in box_files:
            try:
                container = BoxContainer(box_file, f"{tenant_id}:{owner_id}")
                data = container._load()
                files_dict = data.get("files", {})
                for logical_path, b64_content in files_dict.items():
                    import base64
                    raw_bytes = base64.b64decode(b64_content)
                    clean_path = logical_path.lstrip("/")
                    # Categorize logical path into new structure
                    dest_path = self._map_legacy_path(clean_path, target_root)
                    if not dry_run:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        dest_path.write_bytes(raw_bytes)
                    report.files_copied.append(f"[encrypted] {logical_path} -> {dest_path.relative_to(target_root)}")
            except Exception as exc:
                report.warnings.append(f"Failed to decrypt/read container {box_file.name}: {exc}")

        # Look for unencrypted directories or .box.data directories
        for item in owner_dir.iterdir():
            if item.is_file() and item.suffix == ".box":
                continue
            if item.is_dir():
                sub_report = self.migrate_directory(
                    source_dir=item,
                    target_dir=target_root,
                    agent_id=owner_id,
                    dry_run=dry_run,
                    backup=False,
                )
                report.files_copied.extend(sub_report.files_copied)
                report.files_transformed.extend(sub_report.files_transformed)
                report.warnings.extend(sub_report.warnings)
                report.errors.extend(sub_report.errors)

        return report

    def _map_legacy_path(self, clean_path: str, target_root: Path) -> Path:
        """Map legacy logical folder names to standardized Filebox paths."""
        parts = clean_path.split("/")
        top = parts[0] if parts else ""
        rest = "/".join(parts[1:]) if len(parts) > 1 else ""

        if top == "uploads":
            return target_root / "knowledge" / "documents" / (rest or parts[0])
        elif top == "artifacts":
            return target_root / "workspace" / "projects" / "artifacts" / (rest or parts[0])
        elif top == "tmp" or top == "cache":
            return target_root / "workspace" / "scratch" / (rest or parts[0])
        elif top in ("workspace", "memory", "skills", "knowledge", "state", "config", "logs", "identity"):
            return target_root / clean_path
        else:
            return target_root / "workspace" / "drafts" / clean_path
