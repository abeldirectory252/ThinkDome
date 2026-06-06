"""MCP Tool: web_search â€” Search the web with pluggable providers.

Supports DuckDuckGo (default, no API key), Tavily, and Serper.
Rate-limited, sanitized, and audit-logged. Returns structured
results with title, URL, and snippet.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from mcp.types import Tool

from thinkdome.mcp_tools.base import MCPToolBase
from thinkdome.models.search import SearchRequest
from thinkdome.services.search_service import SearchService
from thinkdome.services.audit_service import AuditService
from thinkdome.core.logging import get_logger

logger = get_logger(__name__)


class WebSearchTool(MCPToolBase):
    """Search the web and return structured results.

    Uses DuckDuckGo by default (no API key needed), with optional
    Tavily or Serper backends for higher quality results.
    """

    def __init__(
        self,
        search_service: SearchService,
        audit_service: AuditService,
    ) -> None:
        self._search_service = search_service
        self._audit_service = audit_service

    def tool_definition(self) -> Tool:
        return Tool(
            name="web_search",
            description=(
                "Search the web and return structured results with title, URL, and snippet. "
                "Uses DuckDuckGo by default (no API key needed), with optional "
                "Tavily or Serper backends for higher quality results. "
                "Rate-limited and audit-logged for security. "
                "Use for: researching topics, finding documentation, looking up APIs, "
                "fact-checking claims, gathering technical information, finding code examples, "
                "or checking the latest news on a topic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query string. Be specific for better results. "
                            "Max 500 characters."
                        ),
                        "maxLength": 500,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1-50)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        )

    async def handle(self, arguments: dict[str, Any]) -> str:
        """Execute web search with audit logging."""
        request = SearchRequest(
            query=arguments["query"],
            max_results=arguments.get("max_results", 10),
        )

        start = time.monotonic()

        try:
            result = await self._search_service.search(request)

            # Audit log (fire-and-forget)
            asyncio.create_task(
                self._audit_service.log_search(
                    query=arguments["query"],
                    provider=result.provider,
                    status="success",
                    result_count=result.total_results,
                    duration_ms=result.duration_ms,
                )
            )

            logger.info(
                "web_search_completed",
                query_length=len(arguments["query"]),
                provider=result.provider,
                result_count=result.total_results,
                duration_ms=result.duration_ms,
            )

            return self.success({
                "query": result.query,
                "results": [r.model_dump() for r in result.results],
                "provider": result.provider,
                "total_results": result.total_results,
                "duration_ms": result.duration_ms,
            })

        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000

            # Audit the failure
            asyncio.create_task(
                self._audit_service.log_search(
                    query=arguments["query"],
                    provider=self._search_service.provider.name
                    if self._search_service._provider
                    else "unknown",
                    status="error",
                    error_message=str(e),
                    duration_ms=round(duration_ms, 2),
                )
            )
            raise

