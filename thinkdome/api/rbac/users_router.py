"""User Management REST API Router."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from thinkdome.services.rbac_services import UserService
from thinkdome.repositories.user_repository import UserRepository
from thinkdome.repositories.role_repository import RoleRepository
from thinkdome.models.rbac_models import UserProfile
from thinkdome.api.dependencies import get_current_user

router = APIRouter(prefix="/v1/users", tags=["RBAC Users"])

user_service = UserService()
user_repo = UserRepository()
role_repo = RoleRepository()


class CreateUserRequest(BaseModel):
    username: str = Field(description="Username")
    email: str = Field(description="Email address")
    password: str = Field(description="Initial password")
    first_name: str = Field(default="")
    last_name: str = Field(default="")


class UpdateUserStatusRequest(BaseModel):
    status: str = Field(description="Status: 'active', 'disabled', 'deactivated'")


class AssignRoleRequest(BaseModel):
    role_id: str = Field(description="Role ID to assign")


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    department_id: Optional[str] = None
    designation: Optional[str] = None
    avatar_url: Optional[str] = None


@router.post("", status_code=201)
async def create_user(
    req: CreateUserRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new user account."""
    actor = current_user.get("username", "admin")
    try:
        user = user_service.create_user(
            username=req.username,
            email=req.email,
            password=req.password,
            first_name=req.first_name,
            last_name=req.last_name,
            actor=actor
        )
        return {"status": "success", "user": user.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("")
async def list_users(
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """List users with pagination."""
    users = user_repo.find_all(limit=limit, offset=offset)
    return [u.to_dict() for u in users]


@router.get("/{user_id}")
async def get_user_detail(user_id: str, current_user: dict = Depends(get_current_user)):
    """Fetch user detail, profile, and assigned roles."""
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    profile = user_repo.get_profile(user_id)
    roles = role_repo.get_user_roles(user_id)

    return {
        "user": user.to_dict(),
        "profile": profile.to_dict() if profile else {},
        "roles": [r.to_dict() for r in roles]
    }


@router.patch("/{user_id}/status")
async def update_user_status(
    user_id: str,
    req: UpdateUserStatusRequest,
    current_user: dict = Depends(get_current_user)
):
    """Enable or disable user account."""
    actor = current_user.get("username", "admin")
    try:
        user = user_service.update_user_status(user_id, req.status, actor=actor)
        return {"status": "success", "user": user.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{user_id}/roles")
async def assign_role_to_user(
    user_id: str,
    req: AssignRoleRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assign role to user."""
    actor = current_user.get("username", "admin")
    try:
        user_service.assign_role_to_user(user_id, req.role_id, actor=actor)
        return {"status": "success", "message": "Role assigned successfully."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{user_id}/roles/{role_id}")
async def remove_role_from_user(
    user_id: str,
    role_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove role assignment from user."""
    actor = current_user.get("username", "admin")
    user_service.remove_role_from_user(user_id, role_id, actor=actor)
    return {"status": "success", "message": "Role removed from user."}


@router.put("/{user_id}/profile")
async def update_profile(
    user_id: str,
    req: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update user profile information."""
    profile = user_repo.get_profile(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)

    if req.first_name is not None:
        profile._values["first_name"] = req.first_name
    if req.last_name is not None:
        profile._values["last_name"] = req.last_name
    if req.phone is not None:
        profile._values["phone"] = req.phone
    if req.department_id is not None:
        profile._values["department_id"] = req.department_id
    if req.designation is not None:
        profile._values["designation"] = req.designation
    if req.avatar_url is not None:
        profile._values["avatar_url"] = req.avatar_url

    profile.save()
    return {"status": "success", "profile": profile.to_dict()}
