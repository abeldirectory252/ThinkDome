"""Permission Catalog REST API Router."""

from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Request

from thinkdome.security.rbac.service import PermissionService
from thinkdome.security.repositories.permission import PermissionRepository
from thinkdome.core.dependencies import get_current_admin, get_current_user

router = APIRouter(
    prefix="/v1/permissions",
    tags=["RBAC Permissions"],
    dependencies=[Depends(get_current_admin)],
)

perm_service = PermissionService()
perm_repo = PermissionRepository()


class CreatePermissionRequest(BaseModel):
    module: str = Field(description="Module scope (e.g. 'erp', 'sandbox', 'file')")
    resource: str = Field(description="Resource identifier (e.g. 'finance', 'invoice')")
    action: str = Field(description="Action name (e.g. 'create', 'post_journal', 'approve')")
    description: str = Field(default="", description="Permission description")


@router.post("", status_code=201)
async def create_permission(
    req: CreatePermissionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Dynamically register a new permission catalog item."""
    perm = perm_service.create_permission(
        module=req.module,
        resource=req.resource,
        action=req.action,
        description=req.description
    )
    return {"status": "success", "permission": perm.to_dict()}


@router.get("")
async def list_permissions(request: Request, current_user: dict = Depends(get_current_user)):
    """List persisted grants and available API operations for workspace assignment."""
    action_by_method = {
        "GET": "read", "HEAD": "read", "POST": "create",
        "PUT": "update", "PATCH": "update", "DELETE": "delete",
    }
    for route in request.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/v1/auth/") and path.rsplit("/", 1)[-1] in {"login", "register", "refresh", "me", "logout"}:
            continue
        route_name = getattr(route, "name", None)
        if not route_name:
            continue
        for method in getattr(route, "methods", set()) or set():
            action = action_by_method.get(method)
            if action:
                perm_service.create_permission(
                    module="api",
                    resource=route_name,
                    action=action,
                    description=f"Access API operation {method} {path}",
                )
    perms = perm_repo.find_all()
    return [p.to_dict() for p in perms]
