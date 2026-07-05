"""Custom application exception classes."""

from __future__ import annotations

class SearchError(Exception):
    """Exception raised when a web search provider fails."""

    def __init__(self, message: str, provider: str = "unknown") -> None:
        self.message = message
        self.provider = provider
        super().__init__(self.message)


class RateLimitError(Exception):
    """Exception raised when a rate limit is exceeded."""

    def __init__(self, limit: int, window: str = "minute") -> None:
        self.limit = limit
        self.window = window
        self.message = f"Rate limit of {limit} requests per {window} exceeded."
        super().__init__(self.message)

