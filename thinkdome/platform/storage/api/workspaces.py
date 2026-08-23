"""Workspace management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from thinkdome.core.dependencies import get_workspace_service
from thinkdome.core.dependencies import get_current_user
from thinkdome.platform.storage.workspaces.models import (
    CreateWorkspaceRequest,
    WorkspaceInfo,
    WorkspaceListResponse,
    UpdateWorkspaceRequest,
    SnapshotResponse,
)
from thinkdome.platform.storage.workspaces.service import WorkspaceService

router = APIRouter(tags=["workspaces"])


def _owner(user: dict) -> str:
    return str(user.get("workspace_id", user.get("username", ""))).lower()


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
