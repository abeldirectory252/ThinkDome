"""Workspace and session schemas."""

from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional

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
    owner_id: Optional[str] = None


class WorkspaceMenuItem(BaseModel):
    """One entry in a workspace Desk menu.

    ``page`` targets an existing ThinkDome view, while ``url`` opens a safe
    absolute HTTP(S) URL.  Keeping these explicit makes menu configuration
    data-driven without allowing executable links.
    """

    label: str = Field(min_length=1, max_length=80)
    target_type: Literal["page", "url"] = "page"
    target: str = Field(min_length=1, max_length=2048)
    icon: str = Field(default="grid", max_length=32)


class WorkspaceMenuSection(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    items: list[WorkspaceMenuItem] = Field(default_factory=list, max_length=30)


class WorkspaceMenuRenderItem(BaseModel):
    label: str
    icon: str
    action: Literal["navigate", "external"]
    page: Optional[str] = None
    href: Optional[str] = None


class WorkspaceMenuRenderSection(BaseModel):
    label: str
    items: list[WorkspaceMenuRenderItem] = Field(default_factory=list)


class WorkspaceMenuResponse(BaseModel):
    workspace_id: str
    # ``config`` is retained for the Workspace editor.  Dashboard navigation
    # must use ``menu``, whose actions have already been resolved by the API.
    config: list[WorkspaceMenuSection] = Field(default_factory=list, max_length=12)
    menu: list[WorkspaceMenuRenderSection] = Field(default_factory=list, max_length=12)


class WorkspacePageBlock(BaseModel):
    """A safe, data-only block rendered by the generic Desk page renderer."""
    type: Literal["heading", "text", "metric"]
    title: str = Field(default="", max_length=160)
    body: str = Field(default="", max_length=4000)
    value: str = Field(default="", max_length=160)


class WorkspacePage(BaseModel):
    page_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)
    allowed_roles: list[str] = Field(default_factory=list, max_length=30)
    blocks: list[WorkspacePageBlock] = Field(default_factory=list, max_length=100)


class WorkspacePageListResponse(BaseModel):
    workspace_id: str
    pages: list[WorkspacePage] = Field(default_factory=list)


class UpdateWorkspacePagesRequest(BaseModel):
    pages: list[WorkspacePage] = Field(default_factory=list, max_length=100)


class UpdateWorkspaceMenuRequest(BaseModel):
    sections: list[WorkspaceMenuSection] = Field(default_factory=list, max_length=12)


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
