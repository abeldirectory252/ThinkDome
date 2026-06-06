"""Web search service with pluggable provider interface.

Default provider: DuckDuckGo (no API key required).
Optional providers: Tavily, Serper (require API keys).
All queries are rate-limited, sanitized, and audit-logged.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from thinkdome.core.config import Settings, get_settings
from thinkdome.core.exceptions import SearchError, RateLimitError
from thinkdome.core.logging import get_logger
from thinkdome.core.security import get_search_rate_limiter, sanitize_search_query
from thinkdome.models.search import SearchRequest, SearchResponse, SearchResult

logger = get_logger(__name__)


# â”€â”€ Abstract Provider Interface â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SearchProvider(ABC):
    """Abstract interface for web search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for audit logging."""
        ...

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Execute a search query and return structured results.

        Args:
            query: Sanitized search query.
            max_results: Maximum number of results to return.

        Returns:
            List of SearchResult objects.

        Raises:
            SearchError: If the search fails.
        """
        ...


# â”€â”€ DuckDuckGo Provider (Default â€” No API Key) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo search via the ddgs library (formerly duckduckgo-search).

    Does not require an API key. Uses the DuckDuckGo API
    under the hood for reliable results.
    """

    @property
    def name(self) -> str:
        return "duckduckgo"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5))
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        # Try the new 'ddgs' package first, fall back to old 'duckduckgo_search'
        DDGS = None
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                raise SearchError(
                    "ddgs package not installed. "
                    "Install with: pip install ddgs",
                    provider=self.name,
                )

        try:
            ddgs = DDGS()
            raw_results = ddgs.text(query, max_results=max_results)
            results = []
            for r in raw_results:
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", r.get("link", "")),
                        snippet=r.get("body", r.get("snippet", "")),
                        source=self.name,
                    )
                )
            return results
        except Exception as e:
            raise SearchError(f"DuckDuckGo search failed: {e}", provider=self.name)


# â”€â”€ Tavily Provider (API Key Required) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TavilyProvider(SearchProvider):
    """Tavily AI search API provider.

    Requires TAVILY_API_KEY to be configured.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "tavily"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5))
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for r in data.get("results", []):
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("content", ""),
                            source=self.name,
                        )
                    )
                return results
            except httpx.HTTPError as e:
                raise SearchError(f"Tavily API error: {e}", provider=self.name)


# â”€â”€ Serper Provider (API Key Required) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SerperProvider(SearchProvider):
    """Serper.dev Google Search API provider.

    Requires SERPER_API_KEY to be configured.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "serper"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5))
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    "https://google.serper.dev/search",
                    json={"q": query, "num": max_results},
                    headers={"X-API-KEY": self.api_key},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for r in data.get("organic", []):
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("link", ""),
                            snippet=r.get("snippet", ""),
                            source=self.name,
                        )
                    )
                return results
            except httpx.HTTPError as e:
                raise SearchError(f"Serper API error: {e}", provider=self.name)


# â”€â”€ Search Service (Orchestrator) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SearchService:
    """Web search orchestrator with rate limiting and provider selection.

    Handles:
    - Provider selection based on configuration
    - Input sanitization
    - Rate limiting
    - Structured response formatting
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._provider: Optional[SearchProvider] = None

    @property
    def provider(self) -> SearchProvider:
        """Lazy-load the configured search provider."""
        if self._provider is None:
            self._provider = self._create_provider()
        return self._provider

    def _create_provider(self) -> SearchProvider:
        """Instantiate the configured search provider."""
        name = self.settings.SEARCH_PROVIDER.lower()

        if name == "tavily":
            if not self.settings.TAVILY_API_KEY:
                raise SearchError(
                    "TAVILY_API_KEY is required for Tavily provider",
                    provider="tavily",
                )
            return TavilyProvider(self.settings.TAVILY_API_KEY)

        elif name == "serper":
            if not self.settings.SERPER_API_KEY:
                raise SearchError(
                    "SERPER_API_KEY is required for Serper provider",
                    provider="serper",
                )
            return SerperProvider(self.settings.SERPER_API_KEY)

        else:
            # Default to DuckDuckGo
            return DuckDuckGoProvider()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a web search with rate limiting and sanitization.

        Args:
            request: Structured search request.

        Returns:
            Structured search response with results and metadata.

        Raises:
            RateLimitError: If search rate limit is exceeded.
            SearchError: If the search provider fails.
        """
        # Rate limit check
        limiter = get_search_rate_limiter()
        if not limiter.check("global_search"):
            raise RateLimitError(
                limit=self.settings.SEARCH_RATE_LIMIT,
                window="minute",
            )

        # Sanitize query
        sanitized_query = sanitize_search_query(request.query)
        if not sanitized_query:
            raise SearchError("Empty search query after sanitization", provider="none")

        max_results = min(request.max_results, self.settings.SEARCH_MAX_RESULTS)

        start = time.monotonic()

        try:
            results = await self.provider.search(sanitized_query, max_results)
            duration_ms = (time.monotonic() - start) * 1000

            logger.info(
                f"search_completed: provider={self.provider.name}, "
                f"query_length={len(sanitized_query)}, result_count={len(results)}, "
                f"duration_ms={round(duration_ms, 2)}"
            )

            return SearchResponse(
                query=sanitized_query,
                results=results,
                provider=self.provider.name,
                total_results=len(results),
                duration_ms=round(duration_ms, 2),
            )
        except SearchError:
            raise
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"search_failed: error={str(e)}, provider={self.provider.name}")
            raise SearchError(f"Search failed: {e}", provider=self.provider.name)

