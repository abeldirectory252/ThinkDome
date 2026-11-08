"""Workspace management endpoints."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from thinkdome.core.dependencies import get_workspace_service
from thinkdome.core.dependencies import get_current_admin, get_current_user
from thinkdome.platform.storage.workspaces.models import (
    CreateWorkspaceRequest,
    WorkspaceInfo,
    WorkspaceListResponse,
    UpdateWorkspaceRequest,
    SnapshotResponse,
    UpdateWorkspaceMenuRequest,
    WorkspaceMenuResponse,
    WorkspaceMenuRenderItem,
    WorkspaceMenuRenderSection,
    UpdateWorkspacePagesRequest,
    WorkspacePageListResponse,
)
from thinkdome.platform.storage.workspaces.service import WorkspaceService

router = APIRouter(tags=["workspaces"])


def _owner(user: dict) -> str:
    return str(user.get("workspace_id", user.get("username", ""))).lower()


# This is the server-owned registry for SPA targets.  A browser is never
# allowed to turn an arbitrary menu value into an internal application route.
def _is_admin(user: dict) -> bool:
    from thinkdome.security.identity.core import UserIdentity
    return UserIdentity.from_dict(user).is_admin()


def _is_page_allowed(page, user: dict) -> bool:
    allowed = {role.upper() for role in page.allowed_roles}
    return not allowed or "*" in allowed or str(user.get("role", "")).upper() in allowed


def _menu_response(ws_id: str, sections, pages, user: dict) -> WorkspaceMenuResponse:
    permitted_pages = {page.page_id for page in pages if _is_page_allowed(page, user)}
    rendered_sections = []
    for section in sections:
        entries = []
        for item in section.items:
            if item.target_type == "page" and item.target in permitted_pages:
                entries.append(WorkspaceMenuRenderItem(
                    label=item.label, icon=item.icon, action="navigate", page=item.target
                ))
            else:
                entries.append(WorkspaceMenuRenderItem(
                    label=item.label, icon=item.icon, action="external", href=item.target
                ))
        rendered_sections.append(WorkspaceMenuRenderSection(label=section.label, items=entries))
    if _is_admin(user):
        rendered_sections.append(WorkspaceMenuRenderSection(
            label="Administration",
            items=[WorkspaceMenuRenderItem(
                label="Workspace builder", icon="settings", action="navigate", page="workspaces"
            )],
        ))
    # Regular users get only the resolved, authorized menu. Raw configuration
    # is only returned to the administrative editor.
    return WorkspaceMenuResponse(
        workspace_id=ws_id, config=sections if _is_admin(user) else [], menu=rendered_sections
    )


@router.post("/workspaces", response_model=WorkspaceInfo, status_code=201)
async def create_workspace(
    body: CreateWorkspaceRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
    user: dict = Depends(get_current_user),
):
    return svc.create(body, _owner(user))


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)):
    ws = svc.list_workspaces(_owner(user))
    return WorkspaceListResponse(workspaces=ws)


@router.get("/workspaces/{ws_id}", response_model=WorkspaceInfo)
async def get_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    ws = svc.get(ws_id, _owner(user))
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.put("/workspaces/{ws_id}", response_model=WorkspaceInfo)
async def update_workspace(
    ws_id: str,
    body: UpdateWorkspaceRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
    user: dict = Depends(get_current_user),
):
    ws = svc.update(ws_id, body, _owner(user))
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/workspaces/{ws_id}/menu", response_model=WorkspaceMenuResponse)
async def get_workspace_menu(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    sections = svc.get_menu(ws_id, _owner(user))
    pages = svc.get_pages(ws_id, _owner(user))
    if sections is None or pages is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _menu_response(ws_id, sections, pages, user)


@router.put("/workspaces/{ws_id}/menu", response_model=WorkspaceMenuResponse)
async def update_workspace_menu(
    ws_id: str,
    body: UpdateWorkspaceMenuRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
    user: dict = Depends(get_current_admin),
):
    # Reject unsafe navigation values at the server boundary.  The browser
    # receives only the resolved menu view model below.
    for section in body.sections:
        for item in section.items:
            parsed = urlparse(item.target)
            if item.target_type == "url" and (parsed.scheme not in {"https", "http"} or not parsed.netloc):
                raise HTTPException(status_code=422, detail="Menu URLs must start with http:// or https://")
            if item.target_type == "page":
                pages = svc.get_pages(ws_id, _owner(user))
                if pages is None:
                    raise HTTPException(status_code=404, detail="Workspace not found")
                if item.target not in {page.page_id for page in pages}:
                    raise HTTPException(status_code=422, detail="Menu page target is not a workspace page")
    sections = svc.update_menu(ws_id, body.sections, _owner(user))
    if sections is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    pages = svc.get_pages(ws_id, _owner(user)) or []
    return _menu_response(ws_id, sections, pages, user)


@router.get("/workspaces/{ws_id}/pages", response_model=WorkspacePageListResponse)
async def list_workspace_pages(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    pages = svc.get_pages(ws_id, _owner(user))
    if pages is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    visible = pages if _is_admin(user) else [page for page in pages if _is_page_allowed(page, user)]
    return WorkspacePageListResponse(workspace_id=ws_id, pages=visible)


@router.put("/workspaces/{ws_id}/pages", response_model=WorkspacePageListResponse)
async def update_workspace_pages(
    ws_id: str,
    body: UpdateWorkspacePagesRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
    user: dict = Depends(get_current_admin),
):
    if len({page.page_id for page in body.pages}) != len(body.pages):
        raise HTTPException(status_code=422, detail="Workspace page IDs must be unique")
    from thinkdome.security.repositories.role import RoleRepository
    registered_roles = {role.name.upper() for role in RoleRepository().find_all(limit=1000)}
    for page in body.pages:
        invalid_roles = {
            role.strip().upper() for role in page.allowed_roles
            if role.strip() and role.strip() != "*" and role.strip().upper() not in registered_roles
        }
        if invalid_roles:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown page role(s): {', '.join(sorted(invalid_roles))}",
            )
    pages = svc.update_pages(ws_id, body.pages, _owner(user))
    if pages is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspacePageListResponse(workspace_id=ws_id, pages=pages)


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    if not svc.delete(ws_id, _owner(user)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "deleted", "workspace_id": ws_id}


@router.post("/workspaces/{ws_id}/snapshot", response_model=SnapshotResponse)
async def create_snapshot(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    snap = svc.snapshot(ws_id, _owner(user))
    if not snap:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return snap


@router.post("/workspaces/{ws_id}/restore")
async def restore_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service), user: dict = Depends(get_current_user)
):
    if not svc.restore(ws_id, owner_id=_owner(user)):
        raise HTTPException(status_code=404, detail="No snapshot found")
    return {"status": "restored", "workspace_id": ws_id}


@router.post("/workspaces/{ws_id}/privileges/override")
async def override_workspace_privilege(
    ws_id: str,
    payload: dict,
    svc: WorkspaceService = Depends(get_workspace_service),
    admin: dict = Depends(get_current_admin),
):
    """Override a privilege specifically for this workspace."""
    doc_type = payload.get("document_type", "Page")
    role = payload.get("role", "*")
    permissions = payload.get("permissions", {})
    is_denial = bool(payload.get("is_denial", False))
    is_custom_exempt = bool(payload.get("is_custom_exempt", False))
    level = int(payload.get("level", 0))
    user_id = payload.get("user_id")

    rule = svc.override_privilege(
        ws_id=ws_id,
        document_type=doc_type,
        role=role,
        permissions=permissions,
        is_denial=is_denial,
        is_custom_exempt=is_custom_exempt,
        level=level,
        user_id=user_id,
        actor=admin.get("username", "admin"),
    )
    return {"status": "success", "rule": rule}


@router.get("/workspaces/{ws_id}/privileges/overrides")
async def get_workspace_privilege_overrides(
    ws_id: str,
    svc: WorkspaceService = Depends(get_workspace_service),
    user: dict = Depends(get_current_user),
):
    """List all privilege overrides for this workspace."""
    overrides = svc.get_privilege_overrides(ws_id)
    return {"workspace_id": ws_id, "overrides": overrides}


@router.post("/workspaces/{ws_id}/privileges/reset")
async def reset_workspace_privileges(
    ws_id: str,
    payload: dict = None,
    svc: WorkspaceService = Depends(get_workspace_service),
    admin: dict = Depends(get_current_admin),
):
    """Reset workspace-scoped privilege overrides back to global defaults."""
    doc_type = (payload or {}).get("document_type")
    count = svc.reset_privileges_to_defaults(
        ws_id=ws_id,
        document_type=doc_type,
        actor=admin.get("username", "admin"),
    )
    return {"status": "success", "reset_count": count}
