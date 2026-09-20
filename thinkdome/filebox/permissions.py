"""Path-based permission enforcement for the Filebox filesystem.

Permissions are loaded from ``config/permissions.yaml`` and checked against
every write/delete/append operation.  The permission model is enforced by the
API layer — not by OS-level ACLs — so the AI agent cannot bypass it.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path, PurePosixPath
from typing import Optional

import yaml

from thinkdome.filebox.schemas import AccessLevel, PermissionRule, PermissionsConfig

logger = logging.getLogger(__name__)

# Default permission rules when no config/permissions.yaml exists.
_DEFAULT_RULES: list[dict] = [
    {"path": "identity/**", "access": "read-only"},
    {"path": "config/permissions.yaml", "access": "read-only"},
    {"path": "filebox.yaml", "access": "system-only"},
    {"path": "logs/**", "access": "append-only"},
    {"path": "**/_index.json", "access": "system-only"},
    {"path": "memory/**", "access": "read-write"},
    {"path": "skills/**", "access": "read-write"},
    {"path": "knowledge/**", "access": "read-write"},
    {"path": "workspace/**", "access": "read-write"},
    {"path": "state/**", "access": "read-write"},
    {"path": "config/settings.yaml", "access": "read-write"},
]


class PermissionChecker:
    """Evaluate path-based permission rules against requested operations."""

    def __init__(self, filebox_root: Path):
        self._root = filebox_root
        self._config: Optional[PermissionsConfig] = None

    # ── Loading ──────────────────────────────────────────────────────────

    def _load(self) -> PermissionsConfig:
        if self._config is not None:
            return self._config
        perms_file = self._root / "config" / "permissions.yaml"
        if perms_file.exists():
            try:
                raw = yaml.safe_load(perms_file.read_text(encoding="utf-8")) or {}
                self._config = PermissionsConfig(
                    rules=[PermissionRule(**r) for r in raw.get("rules", [])],
                    defaults=raw.get("defaults", {"access": "read-write"}),
                )
            except Exception:
                logger.warning("Failed to parse permissions.yaml; using defaults")
                self._config = self._defaults()
        else:
            self._config = self._defaults()
        return self._config

    @staticmethod
    def _defaults() -> PermissionsConfig:
        return PermissionsConfig(
            rules=[PermissionRule(**r) for r in _DEFAULT_RULES],
            defaults={"access": "read-write"},
        )

    def reload(self) -> None:
        """Force a re-read of permissions.yaml on next check."""
        self._config = None

    # ── Checking ─────────────────────────────────────────────────────────

    def access_for(self, relative_path: str) -> AccessLevel:
        """Return the effective access level for *relative_path*."""
        config = self._load()
        # Normalise to forward-slash POSIX style.
        rel = str(PurePosixPath(relative_path))
        for rule in config.rules:
            if fnmatch.fnmatch(rel, rule.path):
                return rule.access
        return AccessLevel(config.defaults.get("access", "read-write"))

    def check(
        self,
        relative_path: str,
        operation: str,
        *,
        system: bool = False,
    ) -> bool:
        """Return ``True`` if *operation* is allowed on *relative_path*.

        Parameters
        ----------
        relative_path:
            Path relative to the filebox root (e.g. ``memory/core.md``).
        operation:
            One of ``read``, ``write``, ``delete``, ``append``.
        system:
            If ``True`` the caller is a system/bootstrap process, which is
            allowed to write ``system-only`` paths.
        """
        access = self.access_for(relative_path)

        if operation == "read":
            return True  # Every access level permits reading.

        if access == AccessLevel.SYSTEM_ONLY:
            return system

        if access == AccessLevel.READ_ONLY:
            return False

        if access == AccessLevel.APPEND_ONLY:
            return operation == "append"

        # READ_WRITE
        return True
