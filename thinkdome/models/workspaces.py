"""Workspace and session schemas."""

from __future__ import annotations
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(default="default", max_length=128)
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    quota_mb: int = Field(default=100, ge=1, le=10000)


class WorkspaceInfo(BaseModel):
    workspace_id: str
    name: str
    status: str  # "active" | "archived"
    created_at: datetime
    ttl_seconds: int
    quota_mb: int
    used_mb: float = 0.0
    file_count: int = 0


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceInfo]


class UpdateWorkspaceRequest(BaseModel):
    ttl_seconds: Optional[int] = None
    quota_mb: Optional[int] = None


class SnapshotResponse(BaseModel):
    snapshot_id: str
    workspace_id: str
    created_at: datetime
    size_bytes: int
