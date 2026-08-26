"""Workspace management service."""

from __future__ import annotations

import logging
import json
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
    WorkspaceMenuSection,
    WorkspacePage,
)
from thinkdome.platform.storage.workspaces.entities import WorkspaceDeskMenu, WorkspaceDeskPage, WorkspaceRecord
from thinkdome.platform.storage.workspaces.repository import (
    WorkspaceDeskMenuRepository, WorkspaceDeskPageRepository, WorkspaceRepository,
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
        self._snapshots: dict[str, SnapshotResponse] = {}
        self._workspaces = WorkspaceRepository()
        self._pages = WorkspaceDeskPageRepository()
        self._menus = WorkspaceDeskMenuRepository()

    def get_pages(self, ws_id: str, owner_id: Optional[str] = None) -> Optional[list[WorkspacePage]]:
        if not self.get(ws_id, owner_id):
            return None
        try:
            return [WorkspacePage(
                page_id=record.page_id, title=record.title,
                allowed_roles=json.loads(record.allowed_roles_json), blocks=json.loads(record.blocks_json),
            ) for record in self._pages.for_workspace(ws_id)]
        except (ValueError, TypeError) as exc:
            logger.warning("Could not read workspace pages for %s: %s", ws_id, exc)
            return []

    def update_pages(
        self, ws_id: str, pages: list[WorkspacePage], owner_id: Optional[str] = None
    ) -> Optional[list[WorkspacePage]]:
        if not self.get(ws_id, owner_id):
            return None
        for record in self._pages.for_workspace(ws_id):
            record.delete(soft=False)
        for page in pages:
            WorkspaceDeskPage(
                workspace_id=ws_id, page_id=page.page_id, title=page.title,
                allowed_roles_json=json.dumps(page.allowed_roles), blocks_json=json.dumps([block.model_dump() for block in page.blocks]),
            ).save()
        return pages

    def get_menu(self, ws_id: str, owner_id: Optional[str] = None) -> Optional[list[WorkspaceMenuSection]]:
        if not self.get(ws_id, owner_id):
            return None
        record = self._menus.for_workspace(ws_id)
        if not record:
            return []
        try:
            return [WorkspaceMenuSection.model_validate(section) for section in json.loads(record.sections_json)]
        except (ValueError, TypeError) as exc:
            logger.warning("Could not read workspace menu for %s: %s", ws_id, exc)
            return []

    def update_menu(
        self, ws_id: str, sections: list[WorkspaceMenuSection], owner_id: Optional[str] = None
    ) -> Optional[list[WorkspaceMenuSection]]:
        if not self.get(ws_id, owner_id):
            return None
        record = self._menus.for_workspace(ws_id)
        if not record:
            record = WorkspaceDeskMenu(workspace_id=ws_id)
        record.sections_json = json.dumps([section.model_dump() for section in sections])
        record.save()
        return sections

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
        WorkspaceRecord(
            id=ws_id, name=info.name, status=info.status, created_at=info.created_at.isoformat(),
            ttl_seconds=info.ttl_seconds, quota_mb=info.quota_mb, owner_id=owner_id or "",
        ).save()
        logger.info(f"Workspace created: {ws_id}")
        return info

    def get(self, ws_id: str, owner_id: Optional[str] = None) -> Optional[WorkspaceInfo]:
        record = self._workspaces.get_by_id(ws_id)
        ws = WorkspaceInfo(
            workspace_id=record.id, name=record.name, status=record.status,
            created_at=record.created_at, ttl_seconds=record.ttl_seconds, quota_mb=record.quota_mb,
            owner_id=record.owner_id,
        ) if record else None
        return ws if ws and (owner_id is None or ws.owner_id == owner_id) else None

    def list_workspaces(self, owner_id: Optional[str] = None) -> list[WorkspaceInfo]:
        records = self._workspaces.for_owner(owner_id) if owner_id is not None else self._workspaces.find_all()
        return [WorkspaceInfo(
            workspace_id=record.id, name=record.name, status=record.status, created_at=record.created_at,
            ttl_seconds=record.ttl_seconds, quota_mb=record.quota_mb, owner_id=record.owner_id,
        ) for record in records]

    def update(self, ws_id: str, request: UpdateWorkspaceRequest, owner_id: Optional[str] = None) -> Optional[WorkspaceInfo]:
        ws = self.get(ws_id, owner_id)
        if not ws:
            return None
        if request.ttl_seconds is not None:
            ws.ttl_seconds = request.ttl_seconds
        if request.quota_mb is not None:
            ws.quota_mb = request.quota_mb
        record = self._workspaces.get_by_id(ws_id)
        record.ttl_seconds = ws.ttl_seconds
        record.quota_mb = ws.quota_mb
        record.save()
        return ws

    def delete(self, ws_id: str, owner_id: Optional[str] = None) -> bool:
        ws = self.get(ws_id, owner_id)
        if not ws:
            return False
        for record in self._pages.for_workspace(ws_id):
            record.delete(soft=False)
        menu = self._menus.for_workspace(ws_id)
        if menu:
            menu.delete(soft=False)
        self._workspaces.delete(ws_id, soft=False)
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
