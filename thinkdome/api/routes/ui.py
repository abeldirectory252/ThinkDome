"""FastAPI Routes for ThinkDome Dynamic UI Platform."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

import thinkdome.core.ui as ui
from thinkdome.core.handler import resolve_and_call
from thinkdome.core.handler import SessionContext
from thinkdome.core.dependencies import get_current_user
from thinkdome.security.identity.core import is_admin_role

router = APIRouter(prefix="/v1/ui", tags=["Dynamic UI Platform"])


def _require_admin(user: Dict[str, Any]) -> None:
    """Apply one normalized admin policy to all UI management mutations."""
    roles = user.get("roles") or [user.get("role", "")]
    if not any(is_admin_role(str(role)) for role in roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access is required")


class SetupPayload(BaseModel):
    workspaces: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    pages: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    components: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class DraftPayload(BaseModel):
    draft_id: Optional[str] = None
    title: Optional[str] = "Draft UI Configuration"
    overrides: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class RpcCallPayload(BaseModel):
    method: str
    args: Optional[List[Any]] = Field(default_factory=list)
    kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)


@router.post("/setup")
async def setup_ui(payload: SetupPayload, user: Dict[str, Any] = Depends(get_current_user)):
    """Idempotently set up developer UI configuration."""
    _require_admin(user)
    try:
        return ui.setup(payload.model_dump())
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/effective")
@router.get("/navigation")
async def get_effective_navigation(user: Dict[str, Any] = Depends(get_current_user)):
    """Fetch calculated Effective UI tailored to authenticated user context."""
    user_ctx = {
        "user_id": user.get("username", user.get("user_id", "default")),
        "roles": [user.get("role", "GUEST")],
    }
    return ui.get_effective_ui(user_ctx)


@router.get("/builder")
async def get_ui_builder(user: Dict[str, Any] = Depends(get_current_user)):
    """Fetch UI builder state including developer configs, overrides, drafts, and versions."""
    _require_admin(user)

    user_ctx = {
        "user_id": user.get("username", "admin"),
        "roles": [user.get("role", "ADMIN")],
    }

    effective = ui.get_effective_ui(user_ctx)
    versions = ui.list_versions()

    return {
        "effective": effective,
        "versions": versions,
        "components": list(ui.components._renderers.keys()),
    }


@router.post("/draft")
async def save_ui_draft(payload: DraftPayload, user: Dict[str, Any] = Depends(get_current_user)):
    """Save an administrator UI draft."""
    _require_admin(user)

    user_id = user.get("username", "admin")
    return ui.save_draft(payload.model_dump(), user_id)


@router.post("/preview")
async def preview_ui_draft(draft_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Preview effective UI resulting from draft changes without publishing."""
    _require_admin(user)
    user_ctx = {
        "user_id": user.get("username", "admin"),
        "roles": [user.get("role", "ADMIN")],
    }
    try:
        return ui.preview(draft_id, user_ctx)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/publish")
async def publish_ui_draft(draft_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Publish an administrator draft into published overrides."""
    _require_admin(user)

    user_id = user.get("username", "admin")
    try:
        return ui.publish(draft_id, user_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/versions")
async def list_ui_versions(user: Dict[str, Any] = Depends(get_current_user)):
    """List historical published UI versions."""
    _require_admin(user)
    return ui.list_versions()


@router.post("/versions/{version_id}/restore")
async def restore_ui_version(version_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Restore a historical UI version."""
    _require_admin(user)

    user_id = user.get("username", "admin")
    try:
        return ui.restore_version(version_id, user_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/preferences")
async def get_preferences(user: Dict[str, Any] = Depends(get_current_user)):
    """Get current user preferences."""
    user_id = user.get("username", "default")
    return ui.user_preferences.get(user_id)


@router.post("/preferences")
async def save_preferences(data: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
    """Save current user preferences."""
    user_id = user.get("username", "default")
    return ui.user_preferences.save(data, user_id)


@router.get("/tree")
async def get_tree_view(user: Dict[str, Any] = Depends(get_current_user)):
    """Get tree structure of workspaces, pages, and components."""
    user_ctx = {
        "user_id": user.get("username", "default"),
        "roles": [user.get("role", "GUEST")],
    }
    return ui.get_tree_view(user_ctx)


@router.get("/permissions/matrix")
async def get_role_permission_matrix(user: Dict[str, Any] = Depends(get_current_user)):
    """Get role permission matrix for pages, modules, and processes."""
    _require_admin(user)
    return ui.get_role_permission_matrix()


@router.post("/registry/register")
async def register_entity(config: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
    """Register any UI entity (The Boss endpoint)."""
    _require_admin(user)
    try:
        return ui.register_entity(config)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


class BulkRolePayload(BaseModel):
    entity_type: str
    target_names: List[str]
    role: str
    action: str  # "grant" or "deny"


@router.post("/permissions/bulk")
async def bulk_update_roles(payload: BulkRolePayload, user: Dict[str, Any] = Depends(get_current_user)):
    """Bulk update role access."""
    _require_admin(user)
    return ui.bulk_update_roles(payload.entity_type, payload.target_names, payload.role, payload.action)


@router.get("/registry/summary")
async def get_registry_summary(user: Dict[str, Any] = Depends(get_current_user)):
    """Get full UI platform registry summary."""
    _require_admin(user)
    return ui.get_registry_summary()



# ── Generic RPC Endpoint for await call("method", data) ─────────────────────

rpc_router = APIRouter(prefix="/v1/rpc", tags=["ThinkDome RPC"])


@rpc_router.post("/call")
async def rpc_call(payload: RpcCallPayload, user: Dict[str, Any] = Depends(get_current_user)):
    """Execute whitelisted RPC method."""
    try:
        # resolve_and_call reads the thread-local RPC session. Bind the
        # authenticated HTTP identity so whitelist role checks cannot run as
        # an anonymous/programmatic call.
        with SessionContext(user):
            result = resolve_and_call(payload.method, **payload.kwargs)
        return {"data": result, "error": None}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
