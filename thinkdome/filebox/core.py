"""Filebox core — low-level filesystem API with permission enforcement.

All file operations go through this class so that:
  - Paths are validated (no traversal, no escape)
  - Permissions are checked before every mutation
  - Audit events are emitted for every write/delete
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from thinkdome.filebox.audit import AuditLogger
from thinkdome.filebox.permissions import PermissionChecker
from thinkdome.filebox.schemas import FileNode, FileboxManifest
from thinkdome.filebox.search import FileboxSearch

logger = logging.getLogger(__name__)


class Filebox:
    """The main Filebox filesystem interface.

    Parameters
    ----------
    root:
        Absolute path to the filebox root directory.
    actor:
        Identifier of the current actor (for audit logs).
    """

    # Semantic top-level categories.
    CATEGORIES = (
        "identity",
        "memory",
        "skills",
        "knowledge",
        "workspace",
        "state",
        "config",
        "logs",
    )

    def __init__(self, root: str | Path, *, actor: str = "agent"):
        self._root = Path(root).resolve()
        self._actor = actor
        self._permissions = PermissionChecker(self._root)
        self._audit = AuditLogger(self._root)
        self._search = FileboxSearch(self._root)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def manifest(self) -> FileboxManifest:
        manifest_path = self._root / "filebox.yaml"
        if manifest_path.exists():
            import yaml
            try:
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                return FileboxManifest(**data)
            except Exception:
                pass
        return FileboxManifest()

    @property
    def agent_id(self) -> str:
        return self.manifest.agent_id

    @property
    def version(self) -> str:
        return self.manifest.version

    # ── Path helpers ────────────────────────────────────────────────────

    def _resolve(self, relative_path: str) -> Path:
        """Resolve *relative_path* to an absolute path inside the root.

        Raises ``PermissionError`` if the resolved path escapes the root.
        """
        # Normalise to POSIX-style, strip leading slashes.
        clean = str(PurePosixPath(relative_path)).lstrip("/")
        if not clean or clean == ".":
            return self._root
        resolved = (self._root / clean).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise PermissionError(f"Path traversal blocked: {relative_path}")
        return resolved

    def _relative(self, absolute_path: Path) -> str:
        """Return the relative POSIX path from root."""
        return str(PurePosixPath(absolute_path.relative_to(self._root)))

    def _category_for(self, relative_path: str) -> str:
        """Return the top-level semantic category for a path."""
        parts = PurePosixPath(relative_path.lstrip("/")).parts
        if parts and parts[0] in self.CATEGORIES:
            return parts[0]
        return ""

    # ── Read operations ─────────────────────────────────────────────────

    def read(self, path: str) -> bytes:
        """Read file contents at *path*."""
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        if target.is_dir():
            raise IsADirectoryError(f"Is a directory: {path}")
        return target.read_bytes()

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read file as text."""
        return self.read(path).decode(encoding)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._resolve(path).is_dir()

    def stat(self, path: str) -> dict[str, Any]:
        """Return basic file metadata."""
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        st = target.stat()
        return {
            "path": path,
            "is_dir": target.is_dir(),
            "type": "directory" if target.is_dir() else "file",
            "size": st.st_size if not target.is_dir() else 0,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "created": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
        }

    def list(self, path: str = "") -> list[dict[str, Any]]:
        """List immediate children of *path*."""
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        result = []
        for child in sorted(target.iterdir()):
            rel = self._relative(child)
            st = child.stat()
            result.append({
                "name": child.name,
                "path": rel,
                "is_dir": child.is_dir(),
                "type": "directory" if child.is_dir() else "file",
                "size": st.st_size if not child.is_dir() else 0,
                "modified": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
                "category": self._category_for(rel),
            })
        return result

    def tree(self, path: str = "", *, depth: int = 3) -> FileNode:
        """Build a recursive file tree starting at *path*."""
        target = self._resolve(path)
        rel = self._relative(target) if target != self._root else ""
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        node = FileNode(
            name=target.name or "filebox",
            path=rel,
            is_dir=target.is_dir(),
            type="directory" if target.is_dir() else "file",
            category=self._category_for(rel),
        )
        if target.is_dir() and depth > 0:
            node.children = []
            for child in sorted(target.iterdir()):
                child_rel = self._relative(child)
                if child.is_dir():
                    node.children.append(
                        self.tree(child_rel, depth=depth - 1)
                    )
                else:
                    st = child.stat()
                    mime, _ = mimetypes.guess_type(child.name)
                    node.children.append(FileNode(
                        name=child.name,
                        path=child_rel,
                        is_dir=False,
                        type="file",
                        size=st.st_size,
                        modified=datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        category=self._category_for(child_rel),
                        mime_type=mime or "",
                    ))
        return node

    # ── Write operations ────────────────────────────────────────────────

    def write(
        self,
        path: str,
        content: bytes | str,
        *,
        reason: str = "",
        system: bool = False,
    ) -> Path:
        """Write (create or overwrite) a file at *path*."""
        if not self._permissions.check(path, "write", system=system):
            self._audit.log(
                "write", path, actor=self._actor, reason=reason, result="denied"
            )
            raise PermissionError(f"Write denied: {path}")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        target.write_bytes(content)
        self._audit.log("write", path, actor=self._actor, reason=reason)
        return target

    def append(
        self,
        path: str,
        content: bytes | str,
        *,
        reason: str = "",
        system: bool = False,
    ) -> Path:
        """Append content to a file."""
        if not self._permissions.check(path, "append", system=system):
            self._audit.log(
                "append", path, actor=self._actor, reason=reason, result="denied"
            )
            raise PermissionError(f"Append denied: {path}")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        with target.open("ab") as fh:
            fh.write(content)
        self._audit.log("append", path, actor=self._actor, reason=reason)
        return target

    def delete(
        self,
        path: str,
        *,
        reason: str = "",
        system: bool = False,
    ) -> bool:
        """Delete a file or directory."""
        if not self._permissions.check(path, "delete", system=system):
            self._audit.log(
                "delete", path, actor=self._actor, reason=reason, result="denied"
            )
            raise PermissionError(f"Delete denied: {path}")
        target = self._resolve(path)
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self._audit.log("delete", path, actor=self._actor, reason=reason)
        return True

    def mkdir(self, path: str, *, reason: str = "", system: bool = False) -> Path:
        """Create a directory (and parents)."""
        if not self._permissions.check(path, "write", system=system):
            raise PermissionError(f"Write denied: {path}")
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        self._audit.log("mkdir", path, actor=self._actor, reason=reason)
        return target

    def move(
        self,
        src: str,
        dst: str,
        *,
        reason: str = "",
        system: bool = False,
    ) -> Path:
        """Move/rename a file or directory."""
        if not self._permissions.check(src, "delete", system=system):
            raise PermissionError(f"Delete denied on source: {src}")
        if not self._permissions.check(dst, "write", system=system):
            raise PermissionError(f"Write denied on destination: {dst}")
        src_path = self._resolve(src)
        dst_path = self._resolve(dst)
        if not src_path.exists():
            raise FileNotFoundError(f"Not found: {src}")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        self._audit.log(
            "move", src, actor=self._actor, reason=reason,
            details={"destination": dst},
        )
        return dst_path

    def copy(
        self,
        src: str,
        dst: str,
        *,
        reason: str = "",
        system: bool = False,
    ) -> Path:
        """Copy a file or directory."""
        if not self._permissions.check(dst, "write", system=system):
            raise PermissionError(f"Write denied on destination: {dst}")
        src_path = self._resolve(src)
        dst_path = self._resolve(dst)
        if not src_path.exists():
            raise FileNotFoundError(f"Not found: {src}")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dst_path))
        else:
            shutil.copy2(str(src_path), str(dst_path))
        self._audit.log(
            "copy", src, actor=self._actor, reason=reason,
            details={"destination": dst},
        )
        return dst_path

    # ── Search ──────────────────────────────────────────────────────────

    def search(self, query: str, *, path: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Unified text and indexed search across readable files."""
        return self._search.search(query, path=path, limit=limit)

    def build_index(self, force: bool = False) -> dict[str, Any]:
        """Build or refresh the SQLite FTS5 search index."""
        return self._search.build_index(force=force)

    def search_index(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search the SQLite FTS5 full-text index directly."""
        return self._search.search_index(query, limit=limit)

    @property
    def search_engine(self) -> FileboxSearch:
        return self._search

    # ── Convenience ─────────────────────────────────────────────────────

    @property
    def permissions(self) -> PermissionChecker:
        return self._permissions

    @property
    def audit(self) -> AuditLogger:
        return self._audit
