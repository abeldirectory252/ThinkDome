"""Authentication, API Key, and session management service backed by SQLite database."""

from __future__ import annotations

import os
import json
import hashlib
import secrets
import logging
from typing import Optional, Any, Dict, List
from pathlib import Path
from datetime import datetime
from thinkdome.core.config import Settings
from thinkdome.services.db_service import DatabaseService

logger = logging.getLogger(__name__)

class AuthService:
    """Manages user registration, login, API keys, and session validation using SQLite."""

    def __init__(self, settings: Settings, db_service: DatabaseService) -> None:
        self.settings = settings
        self.db_service = db_service
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        
        # In-memory session store for web dashboards: token -> dict of session info
        self._active_sessions: dict[str, dict] = {}
        
        # Perform schema migrations / JSON data migration
        self._migrate_json_to_db()
        
        # Pre-seed a default admin user if none exists in db
        self._seed_default_admin()

    def _migrate_json_to_db(self) -> None:
        """Migrate existing JSON files into the SQLite database."""
        users_file = self.storage_dir / "users.json"
        keys_file = self.storage_dir / "api_keys.json"

        # Migrate Users
        if users_file.exists():
            try:
                users_data = json.loads(users_file.read_text(encoding="utf-8"))
                for username, info in users_data.items():
                    # Check if already in db
                    exists = self.db_service.fetch_one(
                        "SELECT 1 FROM users WHERE username = ?", (username,)
                    )
                    if not exists:
                        self.db_service.execute(
                            """
                            INSERT INTO users (username, hashed_password, salt, created_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                username,
                                info["hashed_password"],
                                info["salt"],
                                info.get("created_at", datetime.utcnow().isoformat())
                            )
                        )
                        logger.info(f"Migrated user '{username}' to SQLite database.")
                # Rename the file so we don't try to migrate it again
                users_file.rename(users_file.with_suffix(".json.migrated"))
            except Exception as e:
                logger.error(f"Failed to migrate users.json: {e}")

        # Migrate API Keys
        if keys_file.exists():
            try:
                keys_data = json.loads(keys_file.read_text(encoding="utf-8"))
                for token, info in keys_data.items():
                    exists = self.db_service.fetch_one(
                        "SELECT 1 FROM api_keys WHERE token = ?", (token,)
                    )
                    if not exists:
                        self.db_service.execute(
                            """
                            INSERT INTO api_keys (token, key_id, display_name, token_type, created_at, expires_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                token,
                                info["key_id"],
                                info["display_name"],
                                info["token_type"],
                                info.get("created_at", datetime.utcnow().isoformat()),
                                info.get("expires_at"),
                                info.get("status", "active")
                            )
                        )
                        logger.info(f"Migrated API Key '{info['display_name']}' to SQLite database.")
                # Rename the file so we don't try to migrate it again
                keys_file.rename(keys_file.with_suffix(".json.migrated"))
            except Exception as e:
                logger.error(f"Failed to migrate api_keys.json: {e}")

    def _seed_default_admin(self) -> None:
        """Create a default user 'admin' if no users exist."""
        try:
            row = self.db_service.fetch_one("SELECT COUNT(*) as count FROM users")
            if row and row["count"] == 0:
                self.register("admin", "admin123")
                logger.info("Default user 'admin' with password 'admin123' seeded in SQLite database.")
        except Exception as e:
            logger.error(f"Failed to seed default admin: {e}")

    def _hash_password(self, password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    def register(self, username: str, password: str, actor_ip: str = "system") -> bool:
        """Register a new user in the SQLite database and log the audit trail."""
        username = username.strip().lower()
        if not username or not password:
            return False
        
        try:
            exists = self.db_service.fetch_one("SELECT 1 FROM users WHERE username = ?", (username,))
            if exists:
                return False

            salt = secrets.token_hex(16)
            hashed_password = self._hash_password(password, salt)
            created_at = datetime.utcnow().isoformat()
            
            self.db_service.execute(
                """
                INSERT INTO users (username, hashed_password, salt, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (username, hashed_password, salt, created_at)
            )
            
            # Log audit trail
            self.db_service.log_audit(
                actor=username,
                action="register",
                ip_address=actor_ip,
                details={"username": username, "status": "success"}
            )
            logger.info(f"User registered in DB: {username}")
            return True
        except Exception as e:
            logger.error(f"DB registration error for user {username}: {e}")
            return False

    def login(self, username: str, password: str, actor_ip: str = "unknown") -> Optional[str]:
        """Validate credentials against SQLite database, issue a session token, and log audit."""
        username = username.strip().lower()
        try:
            user = self.db_service.fetch_one(
                "SELECT username, hashed_password, salt FROM users WHERE username = ?", (username,)
            )
            if not user:
                self.db_service.log_audit(
                    actor=username,
                    action="login_failure",
                    ip_address=actor_ip,
                    details={"username": username, "reason": "User not found"}
                )
                return None

            hashed = self._hash_password(password, user["salt"])
            if hashed == user["hashed_password"]:
                # Generate session token
                token = f"sk_thinkbox_session_{secrets.token_hex(24)}"
                self._active_sessions[token] = {
                    "username": username,
                    "role": "ADMIN",  # Dashboard admin access
                    "display_name": username
                }
                
                # Log audit trail
                self.db_service.log_audit(
                    actor=username,
                    action="login",
                    ip_address=actor_ip,
                    details={"username": username, "status": "success"}
                )
                logger.info(f"User logged in: {username}")
                return token
            else:
                self.db_service.log_audit(
                    actor=username,
                    action="login_failure",
                    ip_address=actor_ip,
                    details={"username": username, "reason": "Invalid password"}
                )
        except Exception as e:
            logger.error(f"DB login error for user {username}: {e}")
        return None

    def logout(self, token: str, actor_ip: str = "unknown") -> bool:
        """Invalidate a session token and log logout audit."""
        if token in self._active_sessions:
            session = self._active_sessions[token]
            username = session.get("username", "unknown")
            del self._active_sessions[token]
            
            # Log audit
            self.db_service.log_audit(
                actor=username,
                action="logout",
                ip_address=actor_ip,
                details={"username": username}
            )
            return True
        return False

    def verify_token(self, token: str) -> Optional[dict[str, Any]]:
        """Verify session token or API Key from SQLite. Returns token identity info or None."""
        # 1. Check in-memory user sessions
        if token in self._active_sessions:
            return self._active_sessions[token]

        # 2. Check persistent API Keys in SQLite DB
        try:
            key_data = self.db_service.fetch_one(
                "SELECT * FROM api_keys WHERE token = ?", (token,)
            )
            if key_data and key_data.get("status") == "active":
                # Check expiration
                expires_at_str = key_data.get("expires_at")
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.utcnow() > expires_at:
                        logger.warning(f"API key {key_data.get('key_id')} expired")
                        return None
                
                return {
                    "username": "api_key_client",
                    "role": key_data.get("token_type", "LLM"), # LLM or ADMIN
                    "display_name": key_data.get("display_name", "API Key Client"),
                    "key_id": key_data.get("key_id")
                }
        except Exception as e:
            logger.error(f"Error verifying token in database: {e}")

        # 3. Fallback to global config API_KEY
        if self.settings.API_KEY and token == self.settings.API_KEY:
            return {
                "username": "admin",
                "role": "ADMIN",
                "display_name": "Config Admin Key"
            }
            
        return None

    def create_api_key(
        self,
        display_name: str,
        token_type: str = "LLM",
        expires_at: Optional[str] = None,
        creator: str = "admin",
        actor_ip: str = "unknown"
    ) -> dict[str, Any]:
        """Create a new API key in the SQLite database and log audit event."""
        display_name = display_name.strip()[:50] or "Unnamed API Key"
        token_type = "ADMIN" if token_type.upper() == "ADMIN" else "LLM"
        
        # Generate token
        prefix = "sk_tb_" if token_type == "ADMIN" else "gsk_"
        token = f"{prefix}{secrets.token_hex(24)}"
        key_id = f"key_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        
        try:
            self.db_service.execute(
                """
                INSERT INTO api_keys (token, key_id, display_name, token_type, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (token, key_id, display_name, token_type, created_at, expires_at, "active")
            )
            
            # Log audit log
            self.db_service.log_audit(
                actor=creator,
                action="create_api_key",
                ip_address=actor_ip,
                details={
                    "key_id": key_id,
                    "display_name": display_name,
                    "token_type": token_type,
                    "expires_at": expires_at
                }
            )
            
            return {
                "key_id": key_id,
                "display_name": display_name,
                "token_type": token_type,
                "created_at": created_at,
                "expires_at": expires_at,
                "status": "active",
                "token": token
            }
        except Exception as e:
            logger.error(f"Error creating API Key: {e}")
            raise RuntimeError(f"Database error during token generation: {e}")

    def list_api_keys(self) -> list[dict[str, Any]]:
        """List all API keys with masked token for security from the database."""
        try:
            rows = self.db_service.fetch_all(
                "SELECT * FROM api_keys ORDER BY created_at DESC"
            )
            result = []
            for row in rows:
                token = row["token"]
                masked = f"{token[:7]}...{token[-4:]}" if len(token) > 12 else "..."
                key_dict = dict(row)
                del key_dict["token"] # Protect raw token from list
                key_dict["masked_token"] = masked
                result.append(key_dict)
            return result
        except Exception as e:
            logger.error(f"Failed to list API keys: {e}")
            return []

    def revoke_api_key(self, key_id: str, actor: str = "admin", actor_ip: str = "unknown") -> bool:
        """Revoke an API key by ID and write audit entry."""
        try:
            key_data = self.db_service.fetch_one(
                "SELECT display_name FROM api_keys WHERE key_id = ?", (key_id,)
            )
            if not key_data:
                return False
                
            self.db_service.execute(
                "UPDATE api_keys SET status = 'revoked' WHERE key_id = ?",
                (key_id,)
            )
            
            # Log audit log
            self.db_service.log_audit(
                actor=actor,
                action="revoke_api_key",
                ip_address=actor_ip,
                details={
                    "key_id": key_id,
                    "display_name": key_data["display_name"]
                }
            )
            logger.info(f"API Key {key_id} revoked.")
            return True
        except Exception as e:
            logger.error(f"Failed to revoke API key {key_id}: {e}")
            return False

