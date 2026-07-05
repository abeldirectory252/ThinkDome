"""Workspace management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from thinkdome.api.dependencies import get_workspace_service
from thinkdome.models.workspaces import (
    CreateWorkspaceRequest,
    WorkspaceInfo,
    WorkspaceListResponse,
    UpdateWorkspaceRequest,
    SnapshotResponse,
)
from thinkdome.services.workspace_service import WorkspaceService

router = APIRouter(tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceInfo, status_code=201)
async def create_workspace(
    body: CreateWorkspaceRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
):
    return svc.create(body)


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(svc: WorkspaceService = Depends(get_workspace_service)):
    ws = svc.list_workspaces()
    return WorkspaceListResponse(workspaces=ws)


@router.get("/workspaces/{ws_id}", response_model=WorkspaceInfo)
async def get_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service)
):
    ws = svc.get(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.put("/workspaces/{ws_id}", response_model=WorkspaceInfo)
async def update_workspace(
    ws_id: str,
    body: UpdateWorkspaceRequest,
    svc: WorkspaceService = Depends(get_workspace_service),
):
    ws = svc.update(ws_id, body)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service)
):
    if not svc.delete(ws_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "deleted", "workspace_id": ws_id}


@router.post("/workspaces/{ws_id}/snapshot", response_model=SnapshotResponse)
async def create_snapshot(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service)
):
    snap = svc.snapshot(ws_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return snap


@router.post("/workspaces/{ws_id}/restore")
async def restore_workspace(
    ws_id: str, svc: WorkspaceService = Depends(get_workspace_service)
):
    if not svc.restore(ws_id):
        raise HTTPException(status_code=404, detail="No snapshot found")
    return {"status": "restored", "workspace_id": ws_id}
