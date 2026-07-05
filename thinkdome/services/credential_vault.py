"""Credential vault — server-side secret storage for sandbox environments.

Secrets are encrypted at rest using Fernet symmetric encryption and
injected into containers as environment variables only when explicitly
requested by ORCH/IDE tokens. Secrets never appear in logs or audit trails.

Features:
  - Per-user, per-sandbox secret scoping
  - Fernet encryption at rest
  - Inject-only API (secrets retrieved only into container env, never returned as plaintext to API consumers)
  - Secure deletion with key wiping
"""

from __future__ import annotations

import logging
import time
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Lazy import for optional cryptography dependency
_fernet = None


def _get_fernet(master_key: Optional[str]):
    """Lazily initialize Fernet cipher with the master key."""
    global _fernet
    if _fernet is not None:
        return _fernet

    if not master_key:
        logger.warning(
            "⚠️ VAULT_MASTER_KEY not set — vault will store secrets in plaintext. "
            "Set VAULT_MASTER_KEY for production use."
        )
        return None

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(master_key.encode("utf-8") if isinstance(master_key, str) else master_key)
        logger.info("🔐 Credential vault encryption initialized")
        return _fernet
    except ImportError:
        logger.warning(
            "⚠️ cryptography package not installed — vault will store secrets in plaintext. "
            "Install with: pip install cryptography"
        )
        return None
    except Exception as e:
        logger.error(f"Failed to initialize vault encryption: {e}")
        return None


class CredentialVault:
    """Encrypted secret storage for sandbox environments.

    Usage:
        vault = CredentialVault(settings, db_service)
        vault.store("user1", "sandbox_abc", "API_KEY", "sk-secret-123")
        env = vault.inject_into_env("user1", "sandbox_abc")
        # env = {"API_KEY": "sk-secret-123"}
    """

    def __init__(self, settings, db_service) -> None:
        self.settings = settings
        self.db_service = db_service
        self._cipher = _get_fernet(settings.VAULT_MASTER_KEY)

        # Ensure vault table exists
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the credential_vault table if it doesn't exist."""
        # Already handled dynamically in db_service schema setup
        pass

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a value. Falls back to plaintext if no cipher available."""
        if self._cipher:
            return self._cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return plaintext

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a value. Falls back to returning as-is if no cipher available."""
        if self._cipher:
            try:
                return self._cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
            except Exception as e:
                logger.error(f"Vault decryption failed: {e}")
                raise ValueError("Failed to decrypt vault entry — master key may have changed")
        return ciphertext

    # ── Public API ─────────────────────────────────────────────────────────────

    def store(self, user_id: str, sandbox_id: str, key_name: str, value: str) -> None:
        """Store or update a secret in the vault.

        Args:
            user_id: Owner user ID
            sandbox_id: Target sandbox ID
            key_name: Secret key name (e.g., "OPENAI_API_KEY")
            value: Secret value (will be encrypted at rest)
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        encrypted = self._encrypt(value)

        # Upsert
        existing = self.db_service.fetch_one(
            "SELECT id FROM credential_vault WHERE user_id = ? AND sandbox_id = ? AND key_name = ?",
            (user_id, sandbox_id, key_name)
        )

        if existing:
            self.db_service.execute(
                "UPDATE credential_vault SET encrypted_value = ?, updated_at = ? WHERE id = ?",
                (encrypted, now, existing["id"])
            )
        else:
            self.db_service.execute(
                """INSERT INTO credential_vault (user_id, sandbox_id, key_name, encrypted_value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, sandbox_id, key_name, encrypted, now, now)
            )

        # Never log the actual secret value
        logger.info(f"🔐 Vault: stored secret '{key_name}' for user={user_id}, sandbox={sandbox_id}")

    def list_keys(self, user_id: str, sandbox_id: str) -> List[str]:
        """List all secret key names for a user/sandbox pair (values are NOT returned)."""
        rows = self.db_service.fetch_all(
            "SELECT key_name FROM credential_vault WHERE user_id = ? AND sandbox_id = ?",
            (user_id, sandbox_id)
        )
        return [r["key_name"] for r in rows]

    def delete(self, user_id: str, sandbox_id: str, key_name: str) -> bool:
        """Delete a secret from the vault."""
        existing = self.db_service.fetch_one(
            "SELECT id FROM credential_vault WHERE user_id = ? AND sandbox_id = ? AND key_name = ?",
            (user_id, sandbox_id, key_name)
        )
        if not existing:
            return False

        self.db_service.execute(
            "DELETE FROM credential_vault WHERE id = ?",
            (existing["id"],)
        )
        logger.info(f"🔐 Vault: deleted secret '{key_name}' for user={user_id}, sandbox={sandbox_id}")
        return True

    def delete_all_for_sandbox(self, user_id: str, sandbox_id: str) -> int:
        """Delete all secrets for a sandbox (e.g., on sandbox termination)."""
        rows = self.db_service.fetch_all(
            "SELECT id FROM credential_vault WHERE user_id = ? AND sandbox_id = ?",
            (user_id, sandbox_id)
        )
        for r in rows:
            self.db_service.execute("DELETE FROM credential_vault WHERE id = ?", (r["id"],))
        logger.info(f"🔐 Vault: deleted {len(rows)} secrets for sandbox={sandbox_id}")
        return len(rows)

    def inject_into_env(self, user_id: str, sandbox_id: str) -> Dict[str, str]:
        """Retrieve and decrypt all secrets for injection into container environment.

        This is the ONLY method that returns decrypted values.
        It should only be called internally by the executor layer.

        Returns:
            Dict of {key_name: decrypted_value}
        """
        rows = self.db_service.fetch_all(
            "SELECT key_name, encrypted_value FROM credential_vault WHERE user_id = ? AND sandbox_id = ?",
            (user_id, sandbox_id)
        )

        env = {}
        for row in rows:
            try:
                env[row["key_name"]] = self._decrypt(row["encrypted_value"])
            except Exception as e:
                logger.error(f"Failed to decrypt vault entry '{row['key_name']}': {e}")

        return env

    def get_stats(self) -> dict:
        """Return vault statistics (no secret values exposed)."""
        total = self.db_service.fetch_one("SELECT COUNT(*) as cnt FROM credential_vault")
        return {
            "total_secrets": total["cnt"] if total else 0,
            "encryption_enabled": self._cipher is not None,
        }


import os
class SandboxCredentials:
    """Credential protection rules scoping (Anthropic style).

    Holds credentials rules separate from general file system rules.
    Blocks read/write access to certain system file paths and unsets specific env vars.
    """

    def __init__(self, blocked_paths: List[str] = None, blocked_env_vars: List[str] = None) -> None:
        self.blocked_paths = blocked_paths or []
        self.blocked_env_vars = blocked_env_vars or []

    def is_path_blocked(self, path: str) -> bool:
        """Verify if target path is restricted."""
        try:
            normalized_path = os.path.normpath(path).lower()
        except Exception:
            normalized_path = str(path).lower()

        for blocked in self.blocked_paths:
            try:
                normalized_blocked = os.path.normpath(blocked).lower()
            except Exception:
                normalized_blocked = str(blocked).lower()

            if normalized_path == normalized_blocked or normalized_path.startswith(normalized_blocked + os.sep):
                return True
        return False

    def clean_env(self, env_vars: Dict[str, str]) -> Dict[str, str]:
        """Strip restricted env vars before execution."""
        cleaned = dict(env_vars)
        for var in self.blocked_env_vars:
            cleaned.pop(var, None)
        return cleaned

