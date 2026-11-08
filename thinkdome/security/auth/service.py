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

    def __init__(self, settings: Optional[Settings] = None, db_service: Optional[DatabaseService] = None) -> None:
        if settings is None:
            settings = Settings()
        if db_service is None:
            db_service = DatabaseService(settings)
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
                from thinkdome.security.rbac.models import AuthUser
                users_data = json.loads(users_file.read_text(encoding="utf-8"))
                for username, info in users_data.items():
                    existing_user = AuthUser.query().filter(username=username).first()
                    if not existing_user:
                        AuthUser(
                            username=username,
                            hashed_password=info["hashed_password"],
                            salt=info["salt"],
                            created_at=info.get("created_at", datetime.utcnow().isoformat())
                        ).save()
                        logger.info(f"Migrated user '{username}' to SQLite database.")
                # Rename the file so we don't try to migrate it again
                users_file.rename(users_file.with_suffix(".json.migrated"))
            except Exception as e:
                logger.error(f"Failed to migrate users.json: {e}")

        # Migrate API Keys
        if keys_file.exists():
            try:
                from thinkdome.security.rbac.models import ApiKey
                keys_data = json.loads(keys_file.read_text(encoding="utf-8"))
                for token, info in keys_data.items():
                    existing_key = ApiKey.query().filter(token=token).first()
                    if not existing_key:
                        ApiKey(
                            token=token,
                            key_id=info["key_id"],
                            display_name=info["display_name"],
                            token_type=info["token_type"],
                            created_at=info.get("created_at", datetime.utcnow().isoformat()),
                            expires_at=info.get("expires_at"),
                            status=info.get("status", "active")
                        ).save()
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
            from thinkdome.security.rbac.models import AuthUser
            exists = AuthUser.query().filter(username="admin").first()
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
                from thinkdome.security.rbac.protocol import dynamic_role_protocol
                role_repo = RoleRepository()
                admin_role_name = dynamic_role_protocol.get_default_admin_role()
                role = role_repo.get_by_name(admin_role_name)
                if not role:
                    role = Role(name=admin_role_name, description=f"{admin_role_name} platform administrator", is_active=True)
                    role.save()
                if not any(r.id == role.id for r in role_repo.get_user_roles(user.id)):
                    user_service.assign_role_to_user(user.id, role.id, actor="system")
        except Exception as e:
            logger.error(f"Failed to seed default admin: {e}")

    def _hash_password(self, password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    def register(
        self,
        username: str,
        password: str,
        role: Optional[str] = None,
        actor_ip: str = "system",
        email: Optional[str] = None,
        first_name: str = "",
        last_name: str = "",
        phone: str = "",
        department: str = "",
        department_id: Optional[str] = None,
        designation: str = "",
        organization: str = "",
        avatar_url: str = "",
        bio: str = "",
        timezone: str = "UTC",
        locale: str = "en-US",
    ) -> bool:
        """Register a new user in the SQLite database and log the audit trail."""
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        effective_role = role or dynamic_role_protocol.get_default_role()
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,49}", username) or not password:
            return False
        
        try:
            from thinkdome.security.rbac.models import AuthUser
            exists = AuthUser.query().filter(username=username).first()
            if exists:
                return False

            salt = secrets.token_hex(16)
            hashed_password = self._hash_password(password, salt)
            created_at = datetime.utcnow().isoformat()
            
            from thinkdome.security.rbac.registry import rbac_registry
            prof = rbac_registry.get_role_profile(effective_role)
            role_prof_name = prof["name"] if prof else ""

            AuthUser(
                username=username,
                hashed_password=hashed_password,
                salt=salt,
                created_at=created_at,
                role_profile_name=role_prof_name,
            ).save()
            
            # Sync with RBAC UserRepository, RoleProfile & UserRole if available
            try:
                from thinkdome.security.rbac.service import UserService
                from thinkdome.security.repositories.role import RoleRepository
                from thinkdome.security.rbac.models import Role
                user_svc = UserService()
                user = user_svc.user_repo.find_by_username(username)
                if not user:
                    user = user_svc.create_user(
                        username=username,
                        email=email or f"{username}@enterprise.com",
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone,
                        department_id=department_id or (department if department else None),
                        designation=designation,
                        organization=organization,
                        avatar_url=avatar_url,
                        bio=bio,
                        timezone=timezone,
                        locale=locale,
                        actor=username,
                    )
                if role_prof_name and user:
                    rbac_registry.assign_role_profile_to_user(user.username, role_prof_name)
                role_repo = RoleRepository()
                target_role = role_repo.get_by_name(effective_role)
                if not target_role:
                    target_role = Role(name=effective_role, description=f"{effective_role} user role", is_active=True)
                    target_role.save()
                if target_role and user:
                    user_svc.assign_role_to_user(user.id, target_role.id, actor=username)
            except Exception as rbac_error:
                # RBAC synchronization is best-effort
                logger.warning("RBAC user sync note for '%s': %s", username, rbac_error)

            # Log audit trail
            self.db_service.log_audit(
                actor=username,
                action="register",
                ip_address=actor_ip,
                details={"username": username, "role": effective_role, "status": "success"}
            )
            logger.info(f"User registered in DB: {username} with role {effective_role}")
            return True
        except Exception as e:
            logger.error(f"DB registration error for user {username}: {e}")
            return False

    def login(self, username: str, password: str, actor_ip: str = "unknown") -> Optional[str]:
        """Validate credentials against SQLite database, issue a session token, and log audit."""
        username = username.strip().lower()
        try:
            from thinkdome.security.rbac.models import AuthUser
            user = AuthUser.query().filter(username=username).first()
            if not user:
                self.db_service.log_audit(
                    actor=username,
                    action="login_failure",
                    ip_address=actor_ip,
                    details={"username": username, "reason": "User not found"}
                )
                return None

            hashed = self._hash_password(password, user.salt)
            if hashed == user.hashed_password:
                # Generate session token
                from thinkdome.security.rbac.protocol import dynamic_role_protocol
                token = f"sk_thinkbox_session_{secrets.token_hex(24)}"
                role = dynamic_role_protocol.get_default_role()
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
        role: Optional[str] = None,
        tenant_id: str = "default",
        actor_ip: str = "unknown"
    ) -> dict[str, str]:
        """Mint a 15-minute JWT access token and a 7-day rotating refresh token."""
        from thinkdome.security.auth.jwt_engine import (
            create_access_token,
            generate_refresh_token,
            hash_refresh_token
        )
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        effective_role = role or dynamic_role_protocol.get_default_role()
        
        username = username.strip().lower()
        access_token = create_access_token({
            "sub": username,
            "username": username,
            "role": effective_role,
            "tenant_id": tenant_id
        })
        
        raw_refresh = generate_refresh_token()
        hashed_refresh = hash_refresh_token(raw_refresh)
        
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=7)).isoformat()
        
        try:
            from thinkdome.security.rbac.models import AuthRefreshToken
            AuthRefreshToken(
                token_hash=hashed_refresh,
                username=username,
                created_at=now.isoformat(),
                expires_at=expires_at,
                status="active"
            ).save()
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
            from thinkdome.security.rbac.models import AuthRefreshToken
            token_rec = AuthRefreshToken.query().filter(token_hash=hashed, status="active").first()
            if not token_rec:
                return None
                
            expires_at_str = token_rec.expires_at
            if expires_at_str:
                exp_dt = datetime.fromisoformat(expires_at_str)
                if datetime.now(timezone.utc) > exp_dt:
                    token_rec.status = "expired"
                    token_rec.save()
                    return None
            
            # Revoke single-use refresh token
            token_rec.status = "revoked"
            token_rec.save()
            
            username = token_rec.username
            # Fetch user role
            from thinkdome.security.rbac.protocol import dynamic_role_protocol
            user_role = dynamic_role_protocol.get_default_role()
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
        from thinkdome.security.rbac.protocol import dynamic_role_protocol
        jwt_payload = decode_access_token(token)
        if jwt_payload:
            username = jwt_payload.get("sub", jwt_payload.get("username", "anonymous"))
            default_standard_role = dynamic_role_protocol.get_default_role()
            role = jwt_payload.get("role") or default_standard_role
            resolved_roles = [role]
            resolved_permissions: list[str] = []
            resolved_user_id = None
            # Rehydrate RBAC from ORM so a JWT cannot retain a stale
            # default role after an administrator assignment changes.
            try:
                from thinkdome.security.repositories.user import UserRepository
                from thinkdome.security.repositories.role import RoleRepository
                from thinkdome.security.identity.core import select_effective_role
                rbac_user = UserRepository().get_by_username(username)
                if rbac_user:
                    resolved_user_id = rbac_user.id
                    assigned_roles = RoleRepository().get_user_roles(rbac_user.id)
                    resolved_roles = [str(item.name) for item in assigned_roles]
                    resolved_role = select_effective_role(
                        assigned_roles,
                        username=username,
                    )
                    role = resolved_role
                    from thinkdome.security.identity.evaluator import permission_evaluator
                    resolved_permissions = sorted(permission_evaluator.get_effective_permissions(rbac_user.id))
                else:
                    # A validly signed JWT must not retain privileged claims
                    # after its backing user has been deleted.
                    role = default_standard_role
                    resolved_roles = [role]
            except Exception:
                # Fail closed during RBAC outages: preserve authentication for
                # basic access, but never trust a cached privileged JWT claim.
                from thinkdome.security.identity.core import is_admin_role
                if is_admin_role(role):
                    role = default_standard_role
                    resolved_roles = [role]
            return {
                "id": resolved_user_id,
                "username": username,
                "role": role,
                "roles": resolved_roles,
                "permissions": resolved_permissions,
                "tenant_id": jwt_payload.get("tenant_id", "default"),
                "key_id": jwt_payload.get("key_id"),
                "jti": jwt_payload.get("jti"),
                "display_name": jwt_payload.get("sub", "JWT Identity")
            }

        # 2. Check Single-sandbox access tokens
        from thinkdome.security.auth.single_sandbox_token import verify_sandbox_access_token
        sbx_payload = verify_sandbox_access_token(token)
        if sbx_payload:
            default_standard_role = dynamic_role_protocol.get_default_role()
            return {
                "username": sbx_payload.get("sub", "sandbox_client"),
                "role": sbx_payload.get("role") or default_standard_role,
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
                        from thinkdome.security.identity.evaluator import permission_evaluator
                        return {
                            "id": user.id,
                            "username": user.username,
                            "role": select_effective_role(roles, username=user.username),
                            "roles": [role.name for role in roles],
                            "permissions": sorted(permission_evaluator.get_effective_permissions(user.id)),
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

        # 3. Check persistent API Keys in SQLite DB via ORM
        try:
            from thinkdome.security.rbac.models import ApiKey
            key_data = ApiKey.query().filter(token=hashed_token).first()
            if not key_data:
                key_data = ApiKey.query().filter(token=token).first()

            if key_data and getattr(key_data, "status", None) == "active":
                # Check expiration
                expires_at_str = getattr(key_data, "expires_at", None)
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.utcnow() > expires_at:
                        logger.warning(f"API key {getattr(key_data, 'key_id', None)} expired")
                        return None
                
                try:
                    from thinkdome.security.rbac.models import ApiKeyPermission, Permission
                    mappings = ApiKeyPermission.query().filter(key_id=key_data.key_id).all()
                    scoped_permissions = []
                    for mapping in mappings:
                        grant = Permission.get(mapping.permission_id)
                        if grant:
                            scoped_permissions.append(f"{grant.module}:{grant.resource}:{grant.action}".lower())
                except Exception:
                    scoped_permissions = []
                token_type_val = str(getattr(key_data, "token_type", None) or "API_KEY").upper()
                from thinkdome.security.identity.core import is_admin_role
                is_admin_key = is_admin_role(token_type_val) or is_admin_role(getattr(key_data, "role", None))
                role_val = "ADMIN" if is_admin_key else (getattr(key_data, "role", None) or "API_KEY")
                identity = {
                    "username": "admin" if is_admin_key else "api_key_client",
                    # Keep the legacy display/owner name for compatibility,
                    # but provide a unique namespace for persistent storage.
                    "workspace_id": f"api_key_{key_data.key_id}",
                    # API keys carry explicit workspace permission grants; their
                    # credential format never determines a role.
                    "role": role_val,
                    "token_type": token_type_val,
                    "permissions": ["*"] if is_admin_key and not scoped_permissions else scoped_permissions,
                    "display_name": getattr(key_data, "display_name", None) or "API Key Client",
                    "key_id": key_data.key_id
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
        permissions: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
        creator: str = "admin",
        actor_ip: str = "unknown",
        token_type: str = "API_KEY",
    ) -> dict[str, Any]:
        """Create a new API key in the SQLite database and log audit event."""
        display_name = display_name.strip()[:50] or "Unnamed API Key"
        
        permissions = list(dict.fromkeys(permissions or []))
        from thinkdome.security.rbac.models import Permission
        permission_values = []
        for permission_id in permissions:
            permission = Permission.get(permission_id)
            if not permission:
                raise ValueError(f"Unknown workspace permission: {permission_id}")
            permission_values.append(f"{permission.module}:{permission.resource}:{permission.action}".lower())
        token_type = str(token_type or "API_KEY").upper()
        from thinkdome.security.identity.core import is_admin_role
        prefix = "td_admin_" if is_admin_role(token_type) else "td_api_"
        
        # Generate token and metadata
        opaque_part = secrets.token_hex(24)
        token = f"{prefix}{opaque_part}"
        key_id = f"key_{secrets.token_hex(8)}"
        created_at = datetime.utcnow().isoformat()
        
        # Hashing and Masking
        hashed_token = hashlib.sha256(token.encode("utf-8")).hexdigest()
        masked_token = f"{prefix}••••••••{token[-4:]}"
        
        try:
            from thinkdome.security.rbac.models import ApiKey
            ApiKey(
                token=hashed_token,
                key_id=key_id,
                display_name=display_name,
                token_type=token_type,
                created_at=created_at,
                expires_at=expires_at,
                status="active",
                masked_token=masked_token,
            ).save()
            from thinkdome.security.rbac.models import ApiKeyPermission
            for permission_id in permissions:
                ApiKeyPermission(key_id=key_id, permission_id=permission_id).save()
            
            # Log audit log
            self.db_service.log_audit(
                actor=creator,
                action="create_api_key",
                ip_address=actor_ip,
                details={
                    "key_id": key_id,
                    "display_name": display_name,
                    "permissions": permission_values,
                    "expires_at": expires_at
                }
            )
            
            return {
                "key_id": key_id,
                "display_name": display_name,
                "token_type": token_type,
                "permissions": permission_values,
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
            from thinkdome.security.rbac.models import ApiKey
            records = ApiKey.query().all()
            records = sorted(records, key=lambda k: getattr(k, "created_at", "") or "", reverse=True)
            result = []
            for k in records:
                key_dict = {
                    "key_id": k.key_id,
                    "display_name": k.display_name,
                    "token_type": k.token_type,
                    "created_at": k.created_at,
                    "expires_at": k.expires_at,
                    "status": k.status,
                    "masked_token": getattr(k, "masked_token", "") or "••••••••",
                }
                try:
                    from thinkdome.security.rbac.models import ApiKeyPermission, Permission
                    mappings = ApiKeyPermission.query().filter(key_id=k.key_id).all()
                    key_dict["permissions"] = []
                    for mapping in mappings:
                        grant = Permission.get(mapping.permission_id)
                        if grant:
                            key_dict["permissions"].append(f"{grant.module}:{grant.resource}:{grant.action}".lower())
                except Exception:
                    key_dict["permissions"] = []
                result.append(key_dict)
            return result
        except Exception as e:
            logger.error(f"Failed to list API keys: {e}")
            return []

    def revoke_api_key(self, key_id: str, actor: str = "admin", actor_ip: str = "unknown") -> bool:
        """Revoke an API key by ID and write audit entry."""
        try:
            from thinkdome.security.rbac.models import ApiKey
            key_rec = ApiKey.query().filter(key_id=key_id).first()
            if not key_rec:
                return False
                
            key_rec.status = "revoked"
            key_rec.save()
            
            # Evict from verification cache
            token_val = key_rec.token
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
                    "display_name": key_rec.display_name
                }
            )
            logger.info(f"API Key {key_id} revoked.")
            return True
        except Exception as e:
            logger.error(f"Failed to revoke API key {key_id}: {e}")
            return False
