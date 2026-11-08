"""Redis Caching Engine for Dynamic Role Names, Profiles, and Privileges.

Provides microsecond distributed caching backed by Redis with thread-safe
in-memory fallback for local/test environments.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

from thinkdome.core.config import get_settings

logger = logging.getLogger(__name__)


class RbacCache:
    """Enterprise Redis Caching Layer for Dynamic RBAC."""

    _instance: Optional[RbacCache] = None
    _lock = threading.RLock()

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_client = None
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl: int = 600  # 10 minutes

        target_url = redis_url or getattr(get_settings(), "REDIS_URL", "redis://localhost:6379/0")
        if target_url:
            try:
                import redis
                client = redis.Redis.from_url(target_url, decode_responses=True, socket_timeout=1.0)
                client.ping()
                self.redis_client = client
                logger.info("✓ RbacCache successfully connected to Redis: %s", target_url)
            except Exception as exc:
                logger.debug("RbacCache operating in-memory fallback (Redis: %s)", exc)

    @classmethod
    def get_instance(cls) -> RbacCache:
        """Singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _key(self, suffix: str) -> str:
        return f"thinkdome:rbac:{suffix}"

    # ── Role Caching ──────────────────────────────────────────────────────────

    def cache_role(self, role_name: str, role_dict: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache role metadata by role name."""
        norm_name = str(role_name).strip().upper()
        self._set(f"role:{norm_name}", role_dict, ttl)

    def get_role(self, role_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached role metadata by role name."""
        norm_name = str(role_name).strip().upper()
        return self._get(f"role:{norm_name}")

    def invalidate_role(self, role_name: str) -> None:
        """Invalidate cached role and dependent privileges/user roles."""
        norm_name = str(role_name).strip().upper()
        self._delete(f"role:{norm_name}")
        self._delete(f"role_privileges:{norm_name}")
        self._delete("all_roles")
        # Role modification may affect user role resolution
        self.clear_prefix("user_roles:")

    # ── Role Profile Caching ──────────────────────────────────────────────────

    def cache_role_profile(self, profile_name: str, profile_dict: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache role profile (collection of role names) by profile name."""
        norm_name = str(profile_name).strip()
        self._set(f"profile:{norm_name}", profile_dict, ttl)

    def get_role_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached role profile by profile name."""
        norm_name = str(profile_name).strip()
        return self._get(f"profile:{norm_name}")

    def invalidate_profile(self, profile_name: str) -> None:
        """Invalidate role profile and dependent user role caches."""
        norm_name = str(profile_name).strip()
        self._delete(f"profile:{norm_name}")
        self._delete("all_profiles")
        self.clear_prefix("user_roles:")
        self.clear_prefix("user_profile:")

    # ── User Roles Caching ────────────────────────────────────────────────────

    def cache_user_roles(self, username: str, roles: List[str] | Set[str], ttl: Optional[int] = None) -> None:
        """Cache resolved role names for a user."""
        norm_user = str(username).strip().lower()
        self._set(f"user_roles:{norm_user}", sorted(list(roles)), ttl)

    def get_user_roles(self, username: str) -> Optional[List[str]]:
        """Retrieve cached resolved role names for a user."""
        norm_user = str(username).strip().lower()
        return self._get(f"user_roles:{norm_user}")

    def cache_user_profile_name(self, username: str, profile_name: str, ttl: Optional[int] = None) -> None:
        """Cache user's assigned role profile name."""
        norm_user = str(username).strip().lower()
        self._set(f"user_profile:{norm_user}", profile_name, ttl)

    def get_user_profile_name(self, username: str) -> Optional[str]:
        """Retrieve user's assigned role profile name."""
        norm_user = str(username).strip().lower()
        return self._get(f"user_profile:{norm_user}")

    def invalidate_user(self, username: str) -> None:
        """Invalidate user roles and profile cache."""
        norm_user = str(username).strip().lower()
        self._delete(f"user_roles:{norm_user}")
        self._delete(f"user_profile:{norm_user}")

    # ── Role Privileges Caching ───────────────────────────────────────────────

    def cache_role_privileges(self, role_name: str, privileges: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Cache low-level privileges for a role name."""
        norm_name = str(role_name).strip().upper()
        self._set(f"role_privileges:{norm_name}", privileges, ttl)

    def get_role_privileges(self, role_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached low-level privileges for a role name."""
        norm_name = str(role_name).strip().upper()
        return self._get(f"role_privileges:{norm_name}")

    # ── Catalog Listing Caching ───────────────────────────────────────────────

    def cache_all_roles(self, roles: List[Dict[str, Any]], ttl: Optional[int] = None) -> None:
        self._set("all_roles", roles, ttl)

    def get_all_roles(self) -> Optional[List[Dict[str, Any]]]:
        return self._get("all_roles")

    def cache_all_profiles(self, profiles: List[Dict[str, Any]], ttl: Optional[int] = None) -> None:
        self._set("all_profiles", profiles, ttl)

    def get_all_profiles(self) -> Optional[List[Dict[str, Any]]]:
        return self._get("all_profiles")

    # ── Internal Storage & Eviction ───────────────────────────────────────────

    def _get(self, suffix: str) -> Any:
        full_key = self._key(suffix)
        if self.redis_client:
            try:
                raw = self.redis_client.get(full_key)
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass

        with self._lock:
            entry = self._memory_cache.get(full_key)
            if entry:
                if time.time() < entry["expires_at"]:
                    return entry["payload"]
                del self._memory_cache[full_key]
        return None

    def _set(self, suffix: str, payload: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl or self._default_ttl
        full_key = self._key(suffix)
        json_data = json.dumps(payload)

        if self.redis_client:
            try:
                self.redis_client.set(full_key, json_data, ex=effective_ttl)
            except Exception:
                pass

        with self._lock:
            self._memory_cache[full_key] = {
                "payload": payload,
                "expires_at": time.time() + effective_ttl,
            }

    def _delete(self, suffix: str) -> None:
        full_key = self._key(suffix)
        if self.redis_client:
            try:
                self.redis_client.delete(full_key)
            except Exception:
                pass

        with self._lock:
            self._memory_cache.pop(full_key, None)

    def clear_prefix(self, prefix: str) -> None:
        """Clear keys matching a suffix prefix."""
        full_pattern = self._key(f"{prefix}*")
        if self.redis_client:
            try:
                keys = self.redis_client.keys(full_pattern)
                if keys:
                    self.redis_client.delete(*keys)
            except Exception:
                pass

        with self._lock:
            lead = self._key(prefix)
            to_remove = [k for k in self._memory_cache if k.startswith(lead)]
            for k in to_remove:
                del self._memory_cache[k]

    def invalidate_all(self) -> None:
        """Flush all RBAC cache entries."""
        if self.redis_client:
            try:
                keys = self.redis_client.keys(self._key("*"))
                if keys:
                    self.redis_client.delete(*keys)
            except Exception:
                pass

        with self._lock:
            self._memory_cache.clear()


# Global singleton
rbac_cache = RbacCache.get_instance()

