"""Permission Catalog REST API Router."""

from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from thinkdome.services.rbac_services import PermissionService
from thinkdome.repositories.permission_repository import PermissionRepository
from thinkdome.api.dependencies import get_current_user

router = APIRouter(prefix="/v1/permissions", tags=["RBAC Permissions"])

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
async def list_permissions(current_user: dict = Depends(get_current_user)):
    """List all permission catalog items."""
    perms = perm_repo.find_all()
    return [p.to_dict() for p in perms]
