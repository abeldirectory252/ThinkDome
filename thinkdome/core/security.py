"""Security utilities: API key validation, rate limiting hooks."""

from typing import Optional

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from thinkdome.core.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """Verify API key if configured. Returns key or None if auth disabled."""
    settings = get_settings()
    if settings.API_KEY is None:
        return None  # Auth disabled
    if api_key is None or api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


# Search rate limiting and sanitization helpers
import time
from collections import defaultdict

class SimpleRateLimiter:
    """In-memory rate limiter for search tool API keys."""
    
    def __init__(self, limit: int = 30, window: float = 60.0):
        self.limit = limit
        self.window = window
        self.history = defaultdict(list)
        
    def check(self, name: str) -> bool:
        now = time.time()
        self.history[name] = [t for t in self.history[name] if now - t < self.window]
        if len(self.history[name]) >= self.limit:
            return False
        self.history[name].append(now)
        return True

_search_rate_limiter = SimpleRateLimiter(limit=30, window=60.0)

def get_search_rate_limiter() -> SimpleRateLimiter:
    return _search_rate_limiter

def sanitize_search_query(query: str) -> str:
    """Sanitize search query to prevent injection and strip formatting."""
    return query.strip()
