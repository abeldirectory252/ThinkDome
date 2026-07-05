"""File management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response

from thinkdome.api.dependencies import get_file_service
from thinkdome.models.files import (
    FileMetadata,
    FileListResponse,
    FileCopyRequest,
    FileMoveRequest,
    BatchFileOperation,
    BatchOperationResponse,
)
from thinkdome.services.file_service import FileService

router = APIRouter(tags=["files"])


@router.post("/files/upload", response_model=FileMetadata)
async def upload_file(
    file: UploadFile = File(...),
    svc: FileService = Depends(get_file_service),
):
    """Upload a single file."""
    content = await file.read()
    try:
        return svc.upload(file.filename or "upload", content, file.content_type)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))


@router.post("/files/upload/batch", response_model=list[FileMetadata])
async def upload_batch(
    files: list[UploadFile] = File(...),
    svc: FileService = Depends(get_file_service),
):
    """Upload multiple files."""
    results = []
    for f in files:
        content = await f.read()
        try:
            meta = svc.upload(f.filename or "upload", content, f.content_type)
            results.append(meta)
        except ValueError as e:
            raise HTTPException(status_code=413, detail=str(e))
    return results


@router.get("/files", response_model=FileListResponse)
async def list_files(svc: FileService = Depends(get_file_service)):
    """List all uploaded files."""
    files = svc.list_files()
    return FileListResponse(files=files, total=len(files))


@router.get("/files/{file_id}")
async def download_file(file_id: str, svc: FileService = Depends(get_file_service)):
    """Download a file by ID."""
    result = svc.get_content(file_id)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    content, meta = result
    return Response(
        content=content,
        media_type=meta.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{meta.filename}"'},
    )


@router.get("/files/{file_id}/metadata", response_model=FileMetadata)
async def get_file_metadata(
    file_id: str, svc: FileService = Depends(get_file_service)
):
    """Get file metadata."""
    meta = svc.get_metadata(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    return meta


@router.put("/files/{file_id}", response_model=FileMetadata)
async def update_file(
    file_id: str,
    file: UploadFile = File(...),
    svc: FileService = Depends(get_file_service),
):
    """Replace file content."""
    content = await file.read()
    meta = svc.update(file_id, content)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    return meta


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    hard: bool = Query(True, description="Hard delete (remove from disk)"),
    svc: FileService = Depends(get_file_service),
):
    """Delete a file."""
    if not svc.delete(file_id, hard=hard):
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "deleted", "file_id": file_id}


@router.post("/files/{file_id}/copy", response_model=FileMetadata)
async def copy_file(
    file_id: str,
    body: FileCopyRequest,
    svc: FileService = Depends(get_file_service),
):
    """Copy a file."""
    meta = svc.copy_file(file_id, body.new_path)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    return meta


@router.post("/files/{file_id}/move", response_model=FileMetadata)
async def move_file(
    file_id: str,
    body: FileMoveRequest,
    svc: FileService = Depends(get_file_service),
):
    """Move a file."""
    meta = svc.move_file(file_id, body.new_path)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    return meta


@router.post("/files/batch-operation", response_model=BatchOperationResponse)
async def batch_operation(
    body: BatchFileOperation,
    svc: FileService = Depends(get_file_service),
):
    """Bulk file operations."""
    succeeded = []
    failed = []

    for fid in body.file_ids:
        try:
            if body.operation == "delete":
                if svc.delete(fid):
                    succeeded.append(fid)
                else:
                    failed.append({"file_id": fid, "error": "not found"})
            elif body.operation == "move" and body.destination:
                if svc.move_file(fid, body.destination):
                    succeeded.append(fid)
                else:
                    failed.append({"file_id": fid, "error": "not found"})
            else:
                failed.append({"file_id": fid, "error": f"unsupported operation: {body.operation}"})
        except Exception as e:
            failed.append({"file_id": fid, "error": str(e)})

    return BatchOperationResponse(succeeded=succeeded, failed=failed)
