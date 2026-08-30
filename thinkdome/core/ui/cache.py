"""Redis Caching Layer with In-Memory Fallback for Dynamic UI Platform."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from thinkdome.core.config import get_settings

logger = logging.getLogger(__name__)


class UICacheManager:
    """Manages Redis caching for effective UI payloads with in-memory fallback."""

    _instance: Optional[UICacheManager] = None

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_client = None
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = 300

        # Attempt initializing Redis connection
        target_url = redis_url or get_settings().REDIS_URL
        if target_url:
            try:
                import redis
                client = redis.Redis.from_url(target_url, decode_responses=True, socket_timeout=1.0)
                client.ping()
                self.redis_client = client
                logger.info(f"✓ UICacheManager successfully connected to Redis: {target_url}")
            except Exception as e:
                logger.warning(f"UICacheManager operating in memory fallback (Redis unavailable: {e})")

    @classmethod
    def get_instance(cls) -> UICacheManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _make_key(self, key_suffix: str) -> str:
        return f"thinkdome:ui:{key_suffix}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached JSON payload."""
        full_key = self._make_key(key)
        if self.redis_client:
            try:
                data = self.redis_client.get(full_key)
                if data:
                    return json.loads(data)
            except Exception:
                pass

        # Memory cache fallback
        entry = self._memory_cache.get(full_key)
        if entry:
            if time.time() < entry["expires_at"]:
                return entry["payload"]
            else:
                del self._memory_cache[full_key]
        return None

    def set(self, key: str, payload: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
        """Store JSON payload in cache."""
        ttl = ttl_seconds or self._ttl_seconds
        full_key = self._make_key(key)
        json_str = json.dumps(payload)

        if self.redis_client:
            try:
                self.redis_client.set(full_key, json_str, ex=ttl)
            except Exception:
                pass

        # Memory cache store
        self._memory_cache[full_key] = {
            "payload": payload,
            "expires_at": time.time() + ttl,
        }

    def clear(self, key_prefix: str = "") -> None:
        """Invalidate cached entries matching a prefix or clear all UI caches."""
        if self.redis_client:
            try:
                pattern = f"thinkdome:ui:{key_prefix}*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
            except Exception:
                pass

        # Memory cache clear
        prefix = f"thinkdome:ui:{key_prefix}"
        to_delete = [k for k in self._memory_cache if k.startswith(prefix)]
        for k in to_delete:
            del self._memory_cache[k]
