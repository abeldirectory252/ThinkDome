"""Authentication, API Key, and session management service backed by SQLite database."""

from __future__ import annotations

import os
import json
import hashlib
import secrets
import logging
import time
import re
from typing import Optional, Any, Dict, List
from pathlib import Path
from datetime import datetime, timezone, timedelta
from thinkdome.core.config import Settings
from thinkdome.platform.database.service import DatabaseService

logger = logging.getLogger(__name__)

class AuthService:
    """Manages user registration, login, API keys, and session validation using SQLite."""

    def __init__(self, settings: Settings, db_service: DatabaseService) -> None:
        self.settings = settings
        self.db_service = db_service
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        
        # In-memory session store for web dashboards: token -> dict of session info
        self._active_sessions: dict[str, dict] = {}
        
        # In-memory validation cache for API keys: token_hash -> (identity, cache_timestamp)
        self._token_cache: dict[str, tuple[dict[str, Any], float]] = {}
        
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
        """Create a default user 'admin' if it does not exist."""
        # A known password must never be created by a staging/production
        # process. Production administrators are provisioned explicitly.
        if self.settings.DEPLOYMENT_ENV.lower() not in {"development", "test"}:
            logger.info("Skipping development default-admin seed in %s", self.settings.DEPLOYMENT_ENV)
            return
        try:
            exists = self.db_service.fetch_one("SELECT 1 FROM users WHERE username = ?", ("admin",))
            if not exists:
                self.register("admin", "admin123", role="ADMIN")
                logger.info("Default user 'admin' with password 'admin123' seeded in SQLite database.")
            else:
                # Repair databases created before RBAC role assignment was
                # introduced. Authorization still comes from the role table.
                from thinkdome.security.rbac.service import UserService
                from thinkdome.security.repositories.role import RoleRepository
                from thinkdome.security.rbac.models import Role
                user_service = UserService()
                user = user_service.user_repo.find_by_username("admin")
                if not user:
                    user = user_service.create_user(
                        username="admin",
                        email="admin@enterprise.local",
                        password=secrets.token_urlsafe(32),
                        actor="system",
                    )
                role_repo = RoleRepository()
                role = role_repo.get_by_name("ADMIN")
                if not role:
                    role = Role(name="ADMIN", description="Platform administrator", is_active=True)
                    role.save()
                if not any(r.id == role.id for r in role_repo.get_user_roles(user.id)):
                    user_service.assign_role_to_user(user.id, role.id, actor="system")
        except Exception as e:
            logger.error(f"Failed to seed default admin: {e}")

    def _hash_password(self, password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    def register(self, username: str, password: str, role: str = "AGENT_STANDARD", actor_ip: str = "system") -> bool:
        """Register a new user in the SQLite database and log the audit trail."""
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,49}", username) or not password:
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
            
            # Sync with RBAC UserRepository & UserRole if available
            try:
                from thinkdome.security.rbac.service import UserService
                from thinkdome.security.repositories.role import RoleRepository
                user_svc = UserService()
                user = user_svc.user_repo.find_by_username(username)
                if not user:
                    user = user_svc.create_user(
                        username=username,
                        email=f"{username}@enterprise.com",
                        password=password,
                        actor=username
                    )
                role_repo = RoleRepository()
                target_role = role_repo.get_by_name(role)
                if target_role and user:
                    user_svc.assign_role_to_user(user.id, target_role.id, actor=username)
            except Exception as rbac_error:
                # Do not shadow the module-level ``re`` validator used above.
                # RBAC synchronization is best-effort; the primary auth record
                # has already been committed and remains valid.
                logger.warning("RBAC user sync note for '%s': %s", username, rbac_error)

            # Log audit trail
            self.db_service.log_audit(
                actor=username,
                action="register",
                ip_address=actor_ip,
                details={"username": username, "role": role, "status": "success"}
            )
            logger.info(f"User registered in DB: {username} with role {role}")
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
                role = "AGENT_STANDARD"
                try:
                    from thinkdome.security.repositories.user import UserRepository
                    from thinkdome.security.repositories.role import RoleRepository
                    from thinkdome.security.identity.core import select_effective_role
                    rbac_user = UserRepository().get_by_username(username)
                    if rbac_user:
                        role = select_effective_role(
                            RoleRepository().get_user_roles(rbac_user.id),
                            username=username,
                        )
                except Exception:
                    logger.debug("RBAC role lookup unavailable for legacy login", exc_info=True)
                self._active_sessions[token] = {
                    "username": username,
                    "role": role,
                    "display_name": username,
                    "expires_at": time.time() + 900,
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

    def create_auth_tokens(
        self,
        username: str,
        role: str = "AGENT_STANDARD",
        tenant_id: str = "default",
        actor_ip: str = "unknown"
    ) -> dict[str, str]:
        """Mint a 15-minute JWT access token and a 7-day rotating refresh token."""
        from thinkdome.security.auth.jwt_engine import (
            create_access_token,
            generate_refresh_token,
            hash_refresh_token
        )
        
        username = username.strip().lower()
        access_token = create_access_token({
            "sub": username,
            "username": username,
            "role": role,
            "tenant_id": tenant_id
        })
        
        raw_refresh = generate_refresh_token()
        hashed_refresh = hash_refresh_token(raw_refresh)
        
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=7)).isoformat()
        
        try:
            self.db_service.execute(
                """
                INSERT INTO refresh_tokens (token_hash, username, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (hashed_refresh, username, now.isoformat(), expires_at, "active")
            )
        except Exception as e:
            logger.error(f"Error persisting refresh token for {username}: {e}")
            
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "Bearer",
            "expires_in": 900
        }

    def rotate_refresh_token(self, refresh_token: str, actor_ip: str = "unknown") -> Optional[dict[str, str]]:
        """Validate an active refresh token, revoke it, and issue a new access + refresh token pair."""
        from thinkdome.security.auth.jwt_engine import hash_refresh_token
        hashed = hash_refresh_token(refresh_token)
        
        try:
            row = self.db_service.fetch_one(
                "SELECT * FROM refresh_tokens WHERE token_hash = ? AND status = 'active'",
                (hashed,)
            )
            if not row:
                return None
                
            expires_at_str = row.get("expires_at")
            if expires_at_str:
                exp_dt = datetime.fromisoformat(expires_at_str)
                if datetime.now(timezone.utc) > exp_dt:
                    self.db_service.execute(
                        "UPDATE refresh_tokens SET status = 'expired' WHERE token_hash = ?",
                        (hashed,)
                    )
                    return None
            
            # Revoke single-use refresh token
            self.db_service.execute(
                "UPDATE refresh_tokens SET status = 'revoked' WHERE token_hash = ?",
                (hashed,)
            )
            
            username = row["username"]
            # Fetch user role
            user_role = "AGENT_STANDARD"
            try:
                from thinkdome.security.repositories.user import UserRepository
                user_repo = UserRepository()
                user = user_repo.get_by_username(username)
                if user and user.role:
                    user_role = user.role
            except Exception:
                pass
                
            return self.create_auth_tokens(username, role=user_role, actor_ip=actor_ip)
        except Exception as e:
            logger.error(f"Error rotating refresh token: {e}")
            return None

    def verify_token(self, token: str) -> Optional[dict[str, Any]]:
        """Verify JWT access token, single-sandbox token, session token, or API Key."""
        # 1. Check JWT access tokens
        from thinkdome.security.auth.jwt_engine import decode_access_token
        jwt_payload = decode_access_token(token)
        if jwt_payload:
            username = jwt_payload.get("sub", jwt_payload.get("username", "anonymous"))
            role = jwt_payload.get("role", "AGENT_STANDARD")
            # Rehydrate RBAC from ORM so a JWT cannot retain a stale
            # AGENT_STANDARD role after an administrator assignment changes.
            try:
                from thinkdome.security.repositories.user import UserRepository
                from thinkdome.security.repositories.role import RoleRepository
                from thinkdome.security.identity.core import select_effective_role
                rbac_user = UserRepository().get_by_username(username)
                if rbac_user:
                    resolved_role = select_effective_role(
                        RoleRepository().get_user_roles(rbac_user.id),
                        username=username,
                    )
                    role = resolved_role
                else:
                    # A validly signed JWT must not retain privileged claims
                    # after its backing user has been deleted.
                    role = "AGENT_STANDARD"
            except Exception:
                # Fail closed during RBAC outages: preserve authentication for
                # basic access, but never trust a cached privileged JWT claim.
                from thinkdome.security.identity.core import is_admin_role
                if is_admin_role(role):
                    role = "AGENT_STANDARD"
            return {
                "username": username,
                "role": role,
                "tenant_id": jwt_payload.get("tenant_id", "default"),
                "key_id": jwt_payload.get("key_id"),
                "jti": jwt_payload.get("jti"),
                "display_name": jwt_payload.get("sub", "JWT Identity")
            }

        # 2. Check Single-sandbox access tokens
        from thinkdome.security.auth.single_sandbox_token import verify_sandbox_access_token
        sbx_payload = verify_sandbox_access_token(token)
        if sbx_payload:
            return {
                "username": sbx_payload.get("sub", "sandbox_client"),
                "role": sbx_payload.get("role", "AGENT_STANDARD"),
                "sandbox_id": sbx_payload.get("sandbox_id"),
                "token_type": "sandbox_access",
                "display_name": f"Sandbox Token ({sbx_payload.get('sandbox_id')})"
            }

        # 3. Check legacy in-memory user sessions
        if token in self._active_sessions:
            session = self._active_sessions[token]
            if float(session.get("expires_at", 0)) <= time.time():
                self._active_sessions.pop(token, None)
                return None
            return session.copy()

        # RBAC sessions are persisted through the custom ORM repository.
        try:
            from thinkdome.security.repositories.audit import AuditRepository
            from thinkdome.security.repositories.user import UserRepository
            from thinkdome.security.repositories.role import RoleRepository
            from thinkdome.security.identity.core import select_effective_role
            session = AuditRepository().get_session(token)
            if session:
                expires_at = datetime.strptime(session.expires_at, "%Y-%m-%d %H:%M:%S")
                if expires_at > datetime.utcnow():
                    user = UserRepository().get_by_id(session.user_id)
                    if user:
                        roles = RoleRepository().get_user_roles(user.id)
                        return {
                            "id": user.id,
                            "username": user.username,
                            "role": select_effective_role(roles, username=user.username),
                            "roles": [role.name for role in roles],
                            "token_type": "session",
                        }
                return None
        except Exception as exc:
            logger.debug("RBAC session verification unavailable: %s", exc)

        # 2. Check local in-memory token cache
        hashed_token = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        if hashed_token in self._token_cache:
            identity, cache_time = self._token_cache[hashed_token]
            if now - cache_time < 10.0:  # 10s TTL
                return identity.copy()  # Return copy to prevent mutation pollution
            else:
                del self._token_cache[hashed_token]

        # 3. Check persistent API Keys in SQLite DB
        try:
            key_data = self.db_service.fetch_one(
                "SELECT * FROM api_keys WHERE token = ?", (hashed_token,)
            )
            
            # Fallback to plaintext for pre-existing keys or test compatibility
            if not key_data:
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
                
                identity = {
                    "username": "api_key_client",
                    # Keep the legacy display/owner name for compatibility,
                    # but provide a unique namespace for persistent storage.
                    "workspace_id": f"api_key_{key_data.get('key_id')}",
                    "role": key_data.get("token_type", "LLM"), # LLM, WEB, SDK, CURL, ORCH, IDE
                    "display_name": key_data.get("display_name", "API Key Client"),
                    "key_id": key_data.get("key_id")
                }
                # Eviction policy to prevent memory exhaustion (DoS)
                if len(self._token_cache) >= 1000:
                    # Clean up expired items
                    expired_keys = [k for k, (_, t) in self._token_cache.items() if now - t >= 10.0]
                    for k in expired_keys:
                        del self._token_cache[k]
                    # If still too large, drop the oldest (first inserted in python dict)
                    if len(self._token_cache) >= 1000:
                        self._token_cache.pop(next(iter(self._token_cache)))
                
                # Store copy in cache
                self._token_cache[hashed_token] = (identity.copy(), now)
                return identity.copy()
        except Exception as e:
            logger.error(f"Error verifying token in database: {e}")

        # 4. Fallback to global config API_KEY using constant-time comparison (timing attack protection)
        if self.settings.API_KEY and secrets.compare_digest(token, self.settings.API_KEY):
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
        
        token_type = token_type.upper()
        # Map legacy ADMIN token string to ORCH orchestrator token type using framework security constant
        from thinkdome.security.identity.core import ROLE_ADMIN, Role
        if token_type == ROLE_ADMIN or token_type == Role.SUPER_ADMIN.value:
            token_type = "ORCH"
            
        allowed_types = {"LLM", "WEB", "SDK", "CURL", "ORCH", "IDE"}
        if token_type not in allowed_types:
            token_type = "LLM"
            
        prefixes = {
            "LLM": "td_llm_",
            "WEB": "td_web_",
            "SDK": "td_sdk_",
            "CURL": "td_curl_",
            "ORCH": "td_orch_",
            "IDE": "td_ide_"
        }
        prefix = prefixes[token_type]
        
        # Generate token and metadata
        opaque_part = secrets.token_hex(24)
        token = f"{prefix}{opaque_part}"
        key_id = f"key_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        
        # Hashing and Masking
        hashed_token = hashlib.sha256(token.encode("utf-8")).hexdigest()
        masked_token = f"{prefix}••••••••{token[-4:]}"
        
        try:
            self.db_service.execute(
                """
                INSERT INTO api_keys (token, key_id, display_name, token_type, created_at, expires_at, status, masked_token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (hashed_token, key_id, display_name, token_type, created_at, expires_at, "active", masked_token)
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
                key_dict = dict(row)
                if "token" in key_dict:
                    del key_dict["token"] # Protect raw hashed token
                
                # Use stored masked_token if available
                key_dict["masked_token"] = row.get("masked_token") or "••••••••"
                result.append(key_dict)
            return result
        except Exception as e:
            logger.error(f"Failed to list API keys: {e}")
            return []

    def revoke_api_key(self, key_id: str, actor: str = "admin", actor_ip: str = "unknown") -> bool:
        """Revoke an API key by ID and write audit entry."""
        try:
            key_data = self.db_service.fetch_one(
                "SELECT token, display_name FROM api_keys WHERE key_id = ?", (key_id,)
            )
            if not key_data:
                return False
                
            self.db_service.execute(
                "UPDATE api_keys SET status = 'revoked' WHERE key_id = ?",
                (key_id,)
            )
            
            # Evict from verification cache
            token_val = key_data["token"]
            if token_val in self._token_cache:
                del self._token_cache[token_val]
            
            hashed_token = hashlib.sha256(token_val.encode("utf-8")).hexdigest()
            if hashed_token in self._token_cache:
                del self._token_cache[hashed_token]
            
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
