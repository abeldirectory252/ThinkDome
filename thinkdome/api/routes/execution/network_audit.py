"""FastAPI routes for Network Activity Audit Logs & Proxy Stats.

Exposes real-time egress network audit logs, network decision statistics,
and domain rules to API clients and the Web UI Dashboard.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query, Request, status

router = APIRouter(tags=["Network Audit"])


@router.get(
    "/network/audit-log",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "List of recent network egress activity audit logs"},
    },
)
def get_network_audit_log(
    request: Request,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of audit entries"),
    sandbox_id: Optional[str] = Query(None, description="Filter audit logs by sandbox ID"),
) -> dict:
    """Retrieve real-time network egress activity audit logs."""
    egress_proxy = getattr(request.app.state, "egress_proxy", None)
    if not egress_proxy:
        return {"audit_log": [], "count": 0}

    logs = egress_proxy.get_audit_log(limit=limit)
    if sandbox_id:
        logs = [e for e in logs if e.get("sandbox_id") == sandbox_id]

    return {
        "count": len(logs),
        "audit_log": logs,
    }


@router.get(
    "/network/stats",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Network egress proxy statistics"},
    },
)
def get_network_stats(request: Request) -> dict:
    """Retrieve network proxy evaluation statistics (allowed vs denied counts)."""
    egress_proxy = getattr(request.app.state, "egress_proxy", None)
    if not egress_proxy:
        return {"total_evaluations": 0, "allowed": 0, "denied": 0, "total_rules": 0}

    return egress_proxy.get_stats()


@router.get(
    "/network/rules",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "List of active egress domain allowlist rules"},
    },
)
def get_network_rules(request: Request) -> dict:
    """Retrieve active egress domain rules."""
    egress_proxy = getattr(request.app.state, "egress_proxy", None)
    if not egress_proxy:
        return {"rules": [], "count": 0}

    rules = egress_proxy.get_rules()
    return {"count": len(rules), "rules": rules}
