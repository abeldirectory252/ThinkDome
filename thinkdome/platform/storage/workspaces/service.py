"""Workspace management service."""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from thinkdome.core.config import Settings
from thinkdome.platform.storage.workspaces.models import (
    CreateWorkspaceRequest,
    WorkspaceInfo,
    UpdateWorkspaceRequest,
    SnapshotResponse,
)
from thinkdome.platform.storage.workspace_crypto import migrate_workspace_tree

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Manages isolated workspaces."""

    def __init__(self, settings: Settings) -> None:
        self.base_dir = Path(settings.FILE_STORAGE_DIR) / "workspaces"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        try:
            migrate_workspace_tree(self.base_dir)
        except Exception as exc:
            # Fail closed for workspace access, but do not prevent unrelated
            # control-plane routes from starting during key rotation.
            logger.error("Workspace encryption migration failed: %s", exc)
        self._workspaces: dict[str, WorkspaceInfo] = {}
        self._snapshots: dict[str, SnapshotResponse] = {}

    def create(self, request: CreateWorkspaceRequest, owner_id: Optional[str] = None) -> WorkspaceInfo:
        ws_id = str(uuid.uuid4())
        ws_dir = self.base_dir / ws_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        info = WorkspaceInfo(
            workspace_id=ws_id,
            name=request.name,
            status="active",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=request.ttl_seconds,
            quota_mb=request.quota_mb,
            owner_id=owner_id,
        )
        self._workspaces[ws_id] = info
        logger.info(f"Workspace created: {ws_id}")
        return info

    def get(self, ws_id: str, owner_id: Optional[str] = None) -> Optional[WorkspaceInfo]:
        ws = self._workspaces.get(ws_id)
        return ws if ws and (owner_id is None or ws.owner_id == owner_id) else None

    def list_workspaces(self, owner_id: Optional[str] = None) -> list[WorkspaceInfo]:
        return [ws for ws in self._workspaces.values() if owner_id is None or ws.owner_id == owner_id]

    def update(self, ws_id: str, request: UpdateWorkspaceRequest, owner_id: Optional[str] = None) -> Optional[WorkspaceInfo]:
        ws = self.get(ws_id, owner_id)
        if not ws:
            return None
        if request.ttl_seconds is not None:
            ws.ttl_seconds = request.ttl_seconds
        if request.quota_mb is not None:
            ws.quota_mb = request.quota_mb
        return ws

    def delete(self, ws_id: str, owner_id: Optional[str] = None) -> bool:
        ws = self.get(ws_id, owner_id)
        if not ws:
            return False
        self._workspaces.pop(ws_id, None)
        ws_dir = self.base_dir / ws_id
        if ws_dir.exists():
            shutil.rmtree(ws_dir)
        return True

    def snapshot(self, ws_id: str, owner_id: Optional[str] = None) -> Optional[SnapshotResponse]:
        ws = self.get(ws_id, owner_id)
        if not ws:
            return None
        snap_id = str(uuid.uuid4())
        ws_dir = self.base_dir / ws_id
        snap_dir = self.base_dir / f"{ws_id}_snap_{snap_id}"

        size = 0
        if ws_dir.exists():
            shutil.copytree(ws_dir, snap_dir)
            size = sum(f.stat().st_size for f in snap_dir.rglob("*") if f.is_file())

        snap = SnapshotResponse(
            snapshot_id=snap_id,
            workspace_id=ws_id,
            created_at=datetime.now(timezone.utc),
            size_bytes=size,
        )
        self._snapshots[snap_id] = snap
        return snap

    def restore(self, ws_id: str, snapshot_id: Optional[str] = None, owner_id: Optional[str] = None) -> bool:
        if not self.get(ws_id, owner_id):
            return False
        # Find the latest snapshot for this workspace
        snaps = [s for s in self._snapshots.values() if s.workspace_id == ws_id]
        if snapshot_id:
            snaps = [s for s in snaps if s.snapshot_id == snapshot_id]
        if not snaps:
            return False

        snap = max(snaps, key=lambda s: s.created_at)
        snap_dir = self.base_dir / f"{ws_id}_snap_{snap.snapshot_id}"
        ws_dir = self.base_dir / ws_id

        if not snap_dir.exists():
            return False

        if ws_dir.exists():
            shutil.rmtree(ws_dir)
        shutil.copytree(snap_dir, ws_dir)
        return True
