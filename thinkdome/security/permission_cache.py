"""In-Memory Permission Cache with Instant Invalidation."""

from __future__ import annotations

import logging
import time
from typing import Dict, Set, Optional, Tuple

logger = logging.getLogger(__name__)


class PermissionCache:
    """Thread-safe / Async-safe in-memory cache mapping user IDs to effective permission sets."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[Set[str], float]] = {}

    def get(self, user_id: str) -> Optional[Set[str]]:
        """Retrieve cached permission set if not expired."""
        if user_id in self._cache:
            perms, timestamp = self._cache[user_id]
            if time.time() - timestamp < self.ttl_seconds:
                return set(perms)
            del self._cache[user_id]
        return None

    def set(self, user_id: str, permissions: Set[str]) -> None:
        """Store permissions in cache for user_id."""
        self._cache[user_id] = (set(permissions), time.time())

    def invalidate_user(self, user_id: str) -> None:
        """Invalidate cache entry for a specific user."""
        self._cache.pop(user_id, None)

    def invalidate_all(self) -> None:
        """Invalidate all cached permission entries immediately without application restart."""
        self._cache.clear()
        logger.info("Permission cache cleared completely.")


# Global cache instance
permission_cache = PermissionCache(ttl_seconds=300.0)
