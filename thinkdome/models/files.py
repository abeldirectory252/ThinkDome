"""File management schemas."""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FileMetadata(BaseModel):
    """File metadata."""
    file_id: str
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    sha256: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class FileListResponse(BaseModel):
    """Paginated file list."""
    files: list[FileMetadata]
    total: int


class FileCopyRequest(BaseModel):
    new_path: str = Field(..., description="Destination path")


class FileMoveRequest(BaseModel):
    new_path: str = Field(..., description="Destination path")


class BatchFileOperation(BaseModel):
    operation: str = Field(..., description="delete | move | tag")
    file_ids: list[str]
    destination: Optional[str] = None
    tags: Optional[list[str]] = None


class BatchOperationResponse(BaseModel):
    succeeded: list[str]
    failed: list[dict]
