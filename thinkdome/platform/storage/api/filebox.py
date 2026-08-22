"""Authenticated FileBox API."""

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from thinkdome.core.dependencies import get_current_user
from thinkdome.platform.storage.filebox.service import FileBoxService

router = APIRouter(prefix="/v1/filebox", tags=["FileBox"])


class FileBoxCreateRequest(BaseModel):
    filename: str
    content_base64: str
    folder: str = "workspace"
    ttl_seconds: Optional[int] = Field(default=300, ge=1, le=31_536_000)
    permanent: bool = False
    override: bool = False
    conflict: str = "version"


class FileBoxRenewRequest(BaseModel):
    ttl_seconds: int = Field(ge=1, le=31_536_000)


class FileBoxProvisionRequest(BaseModel):
    username: str
    tenant_id: str = "default"
    rotate: bool = False


def _identity(user: dict) -> tuple[str, str]:
    return str(user.get("tenant_id") or "default"), str(user.get("username", "")).strip().lower()


def _service() -> FileBoxService:
    return FileBoxService()


def _public_meta(meta):
    """Return sandbox-safe metadata without host filesystem paths."""
    data = meta.to_dict()
    data.pop("storage_path", None)
    data.pop("root_path", None)
    data["path"] = f"/{meta.folder}/{meta.filename}"
    return data


@router.post("/provision")
async def provision_filebox(req: FileBoxProvisionRequest, user: dict = Depends(get_current_user)):
    if str(user.get("role", "")).upper() not in {"ADMIN", "ADMINISTRATOR", "SUPERADMIN"}:
        raise HTTPException(status_code=403, detail="Only administrators can provision another user's FileBox.")
    owner = req.username.strip().lower()
    service = _service()
    from thinkdome.security.rbac.models import User
    account = User.query().filter(username=owner).first()
    if not account:
        raise HTTPException(status_code=404, detail="User does not exist")
    if account.status != "active":
        raise HTTPException(status_code=409, detail="User is not active")
    existing = service.get_volume(tenant_id=req.tenant_id, owner_id=owner)
    if existing and not req.rotate:
        raise HTTPException(status_code=409, detail="An active FileBox already exists")
    if existing:
        existing._values["status"] = "locked"
        existing.save()
    service.ensure_layout(tenant_id=req.tenant_id, owner_id=owner)
    volume = service.get_volume(tenant_id=req.tenant_id, owner_id=owner)
    container = Path(volume.root_path).parent / Path(volume.root_path).name[:-5]
    return {"status": "created", "owner": owner, "container": container.name}


@router.post("")
async def create_filebox(req: FileBoxCreateRequest, user: dict = Depends(get_current_user)):
    tenant, owner = _identity(user)
    if not owner:
        raise HTTPException(status_code=401, detail="Authenticated owner is required")
    try:
        meta = _service().create(
            tenant_id=tenant,
            owner_id=owner,
            filename=req.filename,
            content=base64.b64decode(req.content_base64, validate=True),
            folder=req.folder,
            ttl_seconds=req.ttl_seconds,
            permanent=req.permanent,
            override=req.override,
            conflict=req.conflict,
        )
        return _public_meta(meta)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/volume")
async def get_filebox_volume(user: dict = Depends(get_current_user)):
    tenant, owner = _identity(user)
    if not owner:
        raise HTTPException(status_code=401, detail="Authenticated owner is required")
    service = _service()
    service.ensure_layout(tenant_id=tenant, owner_id=owner)
    volume = service.get_volume(tenant_id=tenant, owner_id=owner)
    metadata = volume.to_dict()
    # Do not expose host filesystem paths through the API; expose the virtual
    # disk identity and its .box container name instead.
    metadata["container"] = str(metadata.get("container_path") or metadata.get("root_path", "")).split("/")[-1]
    metadata.pop("root_path", None)
    metadata.pop("container_path", None)
    return {"volume": metadata, "folders": list(service.ensure_layout(tenant_id=tenant, owner_id=owner))}


@router.get("/{filebox_id}")
async def read_filebox(filebox_id: str, user: dict = Depends(get_current_user)):
    owner = str(user.get("username", "")).strip().lower()
    tenant = str(user.get("tenant_id") or "default")
    result = _service().read(filebox_id, tenant_id=tenant, owner_id=owner)
    if not result:
        raise HTTPException(status_code=404, detail="FileBox not found or expired")
    content, meta = result
    return {"metadata": _public_meta(meta), "content_base64": base64.b64encode(content).decode("ascii")}


@router.get("")
async def list_fileboxes(user: dict = Depends(get_current_user)):
    owner = str(user.get("username", "")).strip().lower()
    tenant = str(user.get("tenant_id") or "default")
    service = _service()
    return {
        "folders": list(service.ensure_layout(tenant_id=tenant, owner_id=owner)),
        "fileboxes": [_public_meta(item) for item in service.list(tenant_id=tenant, owner_id=owner)],
    }


@router.post("/{filebox_id}/renew")
async def renew_filebox(filebox_id: str, req: FileBoxRenewRequest, user: dict = Depends(get_current_user)):
    owner = str(user.get("username", "")).strip().lower()
    tenant = str(user.get("tenant_id") or "default")
    meta = _service().renew(filebox_id, tenant_id=tenant, owner_id=owner, ttl_seconds=req.ttl_seconds)
    if not meta:
        raise HTTPException(status_code=404, detail="FileBox not found or expired")
    return _public_meta(meta)


@router.post("/{filebox_id}/permanent")
async def make_filebox_permanent(filebox_id: str, user: dict = Depends(get_current_user)):
    owner = str(user.get("username", "")).strip().lower()
    tenant = str(user.get("tenant_id") or "default")
    meta = _service().make_permanent(filebox_id, tenant_id=tenant, owner_id=owner)
    if not meta:
        raise HTTPException(status_code=404, detail="FileBox not found or expired")
    return _public_meta(meta)


@router.delete("/{filebox_id}")
async def delete_filebox(filebox_id: str, user: dict = Depends(get_current_user)):
    owner = str(user.get("username", "")).strip().lower()
    tenant = str(user.get("tenant_id") or "default")
    if not _service().delete(filebox_id, tenant_id=tenant, owner_id=owner):
        raise HTTPException(status_code=404, detail="FileBox not found or expired")
    return {"status": "deleted", "filebox_id": filebox_id}
