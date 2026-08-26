"""Role Profile management."""

import json
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from thinkdome.core.dependencies import get_current_admin
from thinkdome.security.rbac.models import RoleProfile
from thinkdome.security.repositories.base import BaseRepository
from thinkdome.security.repositories.role import RoleRepository

router = APIRouter(prefix="/v1/role-profiles", tags=["RBAC Role Profiles"], dependencies=[Depends(get_current_admin)])
profiles = BaseRepository(RoleProfile)
roles = RoleRepository()

class RoleProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    role_ids: list[str] = Field(default_factory=list, max_length=50)

def _serialize(profile):
    role_ids = json.loads(profile.role_ids_json or "[]")
    return {**profile.to_dict(), "role_ids": role_ids, "roles": [role.name for role in roles.model_class.query().filter(id__in=role_ids).all()]}

@router.get("")
async def list_role_profiles():
    return [_serialize(profile) for profile in profiles.find_all(limit=500)]

@router.post("", status_code=201)
async def create_role_profile(req: RoleProfileRequest):
    if profiles.find_one_by(name=req.name.strip()):
        raise HTTPException(status_code=409, detail="Role Profile already exists")
    missing = [role_id for role_id in req.role_ids if not roles.get_by_id(role_id)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown role IDs: {', '.join(missing)}")
    profile = RoleProfile(name=req.name.strip(), description=req.description, role_ids_json=json.dumps(req.role_ids))
    profile.save()
    return _serialize(profile)

@router.put("/{profile_id}")
async def update_role_profile(profile_id: str, req: RoleProfileRequest):
    profile = profiles.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Role Profile not found")
    missing = [role_id for role_id in req.role_ids if not roles.get_by_id(role_id)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown role IDs: {', '.join(missing)}")
    profile.name = req.name.strip(); profile.description = req.description; profile.role_ids_json = json.dumps(req.role_ids); profile.save()
    return _serialize(profile)
