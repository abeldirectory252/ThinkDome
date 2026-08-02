"""Dynamic Role Management REST API Router."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from thinkdome.security.rbac.service import RoleService
from thinkdome.security.repositories.role import RoleRepository
from thinkdome.core.dependencies import get_current_user
from thinkdome.security.identity.permissions import has_permission, has_role

router = APIRouter(prefix="/v1/roles", tags=["RBAC Roles"])

role_service = RoleService()
role_repo = RoleRepository()


class CreateRoleRequest(BaseModel):
    name: str = Field(description="Unique role name (e.g. FinanceManager)")
    description: str = Field(default="", description="Role description")
    parent_role_id: Optional[str] = Field(default=None, description="Parent role ID for hierarchy")


class AssignPermissionRequest(BaseModel):
    permission_id: str = Field(description="Permission ID to assign")


@router.post("", status_code=201)
async def create_role(
    req: CreateRoleRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new role dynamically without application restart."""
    actor = current_user.get("username", "admin")
    try:
        role = role_service.create_role(
            name=req.name,
            description=req.description,
            parent_role_id=req.parent_role_id,
            actor=actor
        )
        return {"status": "success", "role": role.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("")
async def list_roles(current_user: dict = Depends(get_current_user)):
    """List all registered roles in system."""
    roles = role_repo.find_all()
    return [r.to_dict() for r in roles]


@router.get("/{role_id}")
async def get_role_detail(role_id: str, current_user: dict = Depends(get_current_user)):
    """Get detailed role information including assigned permissions."""
    role = role_repo.get_by_id(role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

    perms = role_repo.get_role_permissions(role_id)
    return {
        "role": role.to_dict(),
        "permissions": [p.to_dict() for p in perms]
    }


@router.delete("/{role_id}")
async def delete_role(role_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a role dynamically."""
    actor = current_user.get("username", "admin")
    try:
        res = role_service.delete_role(role_id, actor=actor)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
        return {"status": "success", "message": "Role deleted successfully."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{role_id}/permissions")
async def assign_permission_to_role(
    role_id: str,
    req: AssignPermissionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assign permission to role dynamically."""
    actor = current_user.get("username", "admin")
    try:
        role_service.assign_permission_to_role(role_id, req.permission_id, actor=actor)
        return {"status": "success", "message": "Permission assigned to role successfully."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{role_id}/permissions/{permission_id}")
async def remove_permission_from_role(
    role_id: str,
    permission_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove permission assignment from role."""
    role_repo.remove_permission_from_role(role_id, permission_id)
    return {"status": "success", "message": "Permission removed from role."}
