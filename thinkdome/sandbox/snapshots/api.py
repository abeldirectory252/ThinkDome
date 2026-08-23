"""Snapshot & Backtrack API endpoints."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from thinkdome.core.dependencies import get_snapshot_service, get_current_user
from thinkdome.sandbox.snapshots.service import SnapshotService

router = APIRouter(tags=["snapshots"], dependencies=[Depends(get_current_user)])


class CreateSnapshotRequest(BaseModel):
    sandbox_id: str = Field(..., description="ID or name of the active sandbox")
    tag: Optional[str] = Field(None, description="Optional tag (e.g. step_1, pre-execution)")
    description: str = Field("", description="Notes or reason for snapshot checkpoint")
    workspace_path: Optional[str] = Field(None, description="Path of workspace to snapshot")


class RestoreSnapshotRequest(BaseModel):
    sandbox_id: str = Field(..., description="Target sandbox ID")
    snapshot_id: str = Field(..., description="ID of the snapshot checkpoint to restore")
    workspace_path: Optional[str] = Field(None, description="Path of workspace to restore into")


@router.post("/snapshots/create", status_code=201)
async def create_snapshot(
    req: CreateSnapshotRequest,
    svc: SnapshotService = Depends(get_snapshot_service),
):
    """Create a point-in-time state snapshot checkpoint for a sandbox."""
    try:
        meta = svc.create_snapshot(
            sandbox_id=req.sandbox_id,
            tag=req.tag,
            description=req.description,
            workspace_path=req.workspace_path,
        )
        return meta
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshots/restore")
async def restore_snapshot(
    req: RestoreSnapshotRequest,
    svc: SnapshotService = Depends(get_snapshot_service),
):
    """Restore a sandbox state back to a previous snapshot checkpoint."""
    try:
        result = svc.restore_snapshot(
            sandbox_id=req.sandbox_id,
            snapshot_id=req.snapshot_id,
            workspace_path=req.workspace_path,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshots")
async def list_snapshots(
    sandbox_id: Optional[str] = None,
    svc: SnapshotService = Depends(get_snapshot_service),
):
    """List all active snapshot checkpoints."""
    return {"snapshots": svc.list_snapshots(sandbox_id=sandbox_id)}


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: str,
    svc: SnapshotService = Depends(get_snapshot_service),
):
    """Delete a snapshot checkpoint and free storage."""
    svc.delete_snapshot(snapshot_id)
    return {"status": "deleted", "snapshot_id": snapshot_id}


@router.get("/snapshots/lineage/{sandbox_id}")
async def get_snapshot_lineage(
    sandbox_id: str,
    svc: SnapshotService = Depends(get_snapshot_service),
):
    """Get the snapshot lineage DAG for workflow visualization and backtracking."""
    return svc.get_lineage(sandbox_id)
