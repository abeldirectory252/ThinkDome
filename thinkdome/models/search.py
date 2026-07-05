"""Web search request/response schemas."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """A single search result entry."""
    title: str
    url: str
    snippet: str
    source: str = ""  # Provider name


class SearchRequest(BaseModel):
    """Web search request parameters."""
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    max_results: int = Field(default=10, ge=1, le=50, description="Maximum results to return")
    region: Optional[str] = Field(None, description="Region code (e.g., 'us-en')")


class SearchResponse(BaseModel):
    """Structured search response."""
    query: str
    results: list[SearchResult]
    provider: str
    total_results: int
    duration_ms: float

