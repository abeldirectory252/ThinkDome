"""Encryption-at-rest helpers for tenant workspaces.

The encryption key is never derived from a username alone.  A deployment
master key (``WORKSPACE_MASTER_KEY`` or ``VAULT_MASTER_KEY``) is preferred;
development installs get a mode-0600 local key file so the application can
bootstrap without putting a key in source control.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from thinkdome.core.config import get_workspace_root, get_settings

_MAGIC = b"TDW1:"


class WorkspaceCipher:
    def __init__(self, username: str):
        if not username or username in {"anonymous", "api_key_client"}:
            raise PermissionError("Authenticated workspace identity is required.")
        settings = get_settings()
        master = getattr(settings, "WORKSPACE_MASTER_KEY", None) or getattr(settings, "VAULT_MASTER_KEY", None)
        if not master:
            storage_dir = Path(get_settings().FILE_STORAGE_DIR)
            if not storage_dir.is_absolute():
                storage_dir = get_workspace_root() / storage_dir
            key_path = storage_dir / ".workspace_master.key"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            if key_path.exists():
                master = key_path.read_text(encoding="utf-8").strip()
            else:
                master = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
                key_path.write_text(master, encoding="utf-8")
                os.chmod(key_path, 0o600)
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as exc:
            raise RuntimeError("Workspace encryption requires the 'cryptography' package.") from exc
        digest = hashlib.sha256(f"{master}:{username}".encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._invalid = InvalidToken

    def encrypt(self, data: bytes) -> bytes:
        return _MAGIC + self._fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        if not data.startswith(_MAGIC):
            # Legacy plaintext is accepted once, then rewritten encrypted by
            # the caller. This supports safe migration without data loss.
            return data
        try:
            return self._fernet.decrypt(data[len(_MAGIC):])
        except self._invalid as exc:
            raise PermissionError("Workspace file cannot be decrypted with this tenant key.") from exc

    def read(self, path: Path) -> bytes:
        raw = path.read_bytes()
        clear = self.decrypt(raw)
        if not raw.startswith(_MAGIC):
            path.write_bytes(self.encrypt(clear))
        return clear

    def write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.encrypt(data))


def workspace_cipher(username: str) -> WorkspaceCipher:
    return WorkspaceCipher(username)


def migrate_workspace_tree(base_dir: Path) -> int:
    """Encrypt legacy plaintext user files once at service startup."""
    migrated = 0
    if not base_dir.exists():
        return migrated
    for user_dir in base_dir.iterdir():
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        cipher = WorkspaceCipher(user_dir.name)
        for path in user_dir.rglob("*"):
            if not path.is_file() or ".pip_packages" in path.parts:
                continue
            raw = path.read_bytes()
            if not raw.startswith(_MAGIC):
                path.write_bytes(cipher.encrypt(raw))
                migrated += 1
    return migrated
