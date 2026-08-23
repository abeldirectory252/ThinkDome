"""FastAPI route for SDK metrics ingestion.

Accepts best-effort telemetry events from client SDKs (e.g. sandbox creation duration, execution time)
and parses SDK User-Agent headers to correlate performance metrics.

Inspired by OpenSandbox's metrics ingestion API.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
from thinkdome.core.dependencies import get_current_user

router = APIRouter(tags=["Metrics"], dependencies=[Depends(get_current_user)])

# Match pattern: ThinkDome-Python-SDK/0.1.0, ThinkDome-Go-SDK/1.0.0, etc.
_SDK_USER_AGENT_RE = re.compile(
    r"(?:ThinkDome|OpenSandbox)-([A-Za-z0-9]+)-SDK/([^\s]+)",
    re.IGNORECASE,
)


class MetricsEvent(BaseModel):
    """Schema for SDK metrics event report."""
    event_type: str = Field(..., description="Type of event, e.g., 'sandbox.create', 'code.exec'")
    sandbox_id: Optional[str] = Field(None, description="Target sandbox ID")
    image: Optional[str] = Field(None, description="Container image used")
    create_duration_ms: Optional[float] = Field(None, description="Creation duration in milliseconds")
    exec_duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    success: bool = Field(True, description="Whether the operation succeeded")


def parse_sdk_user_agent(user_agent: Optional[str]) -> tuple[str, str]:
    """Extract (language, version) from SDK User-Agent header."""
    if not user_agent:
        return "unknown", "unknown"
    match = _SDK_USER_AGENT_RE.search(user_agent)
    if not match:
        return "unknown", "unknown"
    return match.group(1).lower(), match.group(2)


@router.post(
    "/metrics/events",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Metrics event accepted"},
        400: {"description": "Bad request"},
    },
)
def report_metrics_event(
    event: MetricsEvent,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    user_agent: Optional[str] = Header(None, alias="User-Agent"),
) -> Response:
    """Accept best-effort SDK metrics events."""
    sdk_language, sdk_version = parse_sdk_user_agent(user_agent)

    logger.debug(
        "Accepted SDK metrics event: type=%s sandbox_id=%s duration_ms=%s sdk=%s/%s success=%s",
        event.event_type,
        event.sandbox_id,
        event.create_duration_ms or event.exec_duration_ms,
        sdk_language,
        sdk_version,
        event.success,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
