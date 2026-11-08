"""Role Profile management with dynamic collection of low-level role names and Redis caching."""

import json
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from thinkdome.core.dependencies import get_current_admin
from thinkdome.security.rbac.models import RoleProfile, Role
from thinkdome.security.repositories.base import BaseRepository
from thinkdome.security.repositories.role import RoleRepository
from thinkdome.security.rbac.registry import rbac_registry
from thinkdome.security.rbac.cache import rbac_cache

router = APIRouter(prefix="/v1/role-profiles", tags=["RBAC Role Profiles"], dependencies=[Depends(get_current_admin)])
profiles = BaseRepository(RoleProfile)
roles = RoleRepository()


class RoleProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    role_ids: list[str] = Field(default_factory=list, max_length=50)
    role_names: list[str] = Field(default_factory=list, max_length=50)


class AssignProfileRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)


def _serialize(profile: RoleProfile):
    role_ids = json.loads(profile.role_ids_json or "[]")
    role_names = []
    if getattr(profile, "role_names_json", None):
        try:
            role_names = json.loads(profile.role_names_json)
        except Exception:
            role_names = []
    if not role_names and role_ids:
        role_names = [role.name for role in roles.model_class.query().filter(id__in=role_ids).all()]
    
    return {
        **profile.to_dict(),
        "role_ids": role_ids,
        "role_names": role_names,
        "roles": role_names,
    }


@router.get("")
async def list_role_profiles():
    return [_serialize(profile) for profile in profiles.find_all(limit=500)]


@router.post("", status_code=201)
async def create_role_profile(req: RoleProfileRequest):
    if profiles.find_one_by(name=req.name.strip()):
        raise HTTPException(status_code=409, detail="Role Profile already exists")

    # Combine role_names and role_ids
    collected_names = list(dict.fromkeys([str(r).strip().upper() for r in req.role_names if str(r).strip()]))
    for role_id in req.role_ids:
        r_obj = roles.get_by_id(role_id)
        if r_obj and r_obj.name.upper() not in collected_names:
            collected_names.append(r_obj.name.upper())

    profile = rbac_registry.register_role_profile(
        name=req.name.strip(),
        description=req.description,
        role_names=collected_names,
    )
    return _serialize(profile)


@router.put("/{profile_id}")
async def update_role_profile(profile_id: str, req: RoleProfileRequest):
    profile = profiles.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Role Profile not found")

    collected_names = list(dict.fromkeys([str(r).strip().upper() for r in req.role_names if str(r).strip()]))
    for role_id in req.role_ids:
        r_obj = roles.get_by_id(role_id)
        if r_obj and r_obj.name.upper() not in collected_names:
            collected_names.append(r_obj.name.upper())

    profile = rbac_registry.register_role_profile(
        name=req.name.strip(),
        description=req.description,
        role_names=collected_names,
    )
    return _serialize(profile)


@router.post("/{profile_id}/assign")
async def assign_role_profile_to_user(profile_id: str, req: AssignProfileRequest):
    profile = profiles.get_by_id(profile_id) or profiles.find_one_by(name=profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Role Profile not found")

    success = rbac_registry.assign_role_profile_to_user(
        username_or_id=req.username.strip(),
        profile_name_or_id=profile.name,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"User '{req.username}' not found")

    assigned_roles = list(rbac_registry.get_user_roles(req.username.strip()))
    return {
        "status": "success",
        "username": req.username,
        "profile": profile.name,
        "assigned_roles": assigned_roles,
    }
