"""Audit Logs and Login History REST API Router."""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends
from thinkdome.security.repositories.audit import AuditRepository
from thinkdome.security.rbac.models import LoginHistory
from thinkdome.core.dependencies import get_current_admin, get_current_user

router = APIRouter(
    prefix="/v1/audit",
    tags=["RBAC Audit"],
    dependencies=[Depends(get_current_admin)],
)

audit_repo = AuditRepository()


@router.get("/logs")
async def list_audit_logs(
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Retrieve RBAC audit trail log records."""
    logs = audit_repo.find_all(limit=limit, offset=offset)
    return [l.to_dict() for l in logs]


@router.get("/logins")
async def list_login_history(
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Retrieve user login histories."""
    histories = LoginHistory.query().limit(limit).offset(offset).all()
    return [h.to_dict() for h in histories]
