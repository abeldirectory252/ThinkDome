"""Filebox Browse API — REST endpoints for tree navigation, file read/write.

Provides a web-friendly interface on top of the core Filebox filesystem
for the Filebox Web UI.  Supports multi-user and multi-tenant scoping,
with role-based access for administrators to inspect and manage team fileboxes.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from thinkdome.core.config import get_settings, get_workspace_root
from thinkdome.core.dependencies import get_current_user
from thinkdome.core.events.events import bus as event_bus
from thinkdome.filebox import bootstrap
from thinkdome.filebox.core import Filebox
from thinkdome.filebox.migration import FileboxMigrator
from thinkdome.security.identity.core import is_admin_role

router = APIRouter(prefix="/v1/filebox/browse", tags=["Filebox Browser"])


# ── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_storage_dir() -> Path:
    settings = get_settings()
    storage_dir = Path(settings.FILE_STORAGE_DIR)
    if not storage_dir.is_absolute():
        storage_dir = get_workspace_root() / storage_dir
    return storage_dir


def _is_admin(user: dict[str, Any]) -> bool:
    roles = user.get("roles") or [user.get("role", "")]
    return any(is_admin_role(str(r)) for r in roles)


def _filebox_root_for(user: dict[str, Any], target_owner: Optional[str] = None) -> Path:
    """Resolve the Filebox root directory for the target owner within the tenant.

    Enforces multi-user isolation: regular users can only access their own
    Filebox, while administrators can access other users' fileboxes within the tenant.
    """
    storage_dir = _resolve_storage_dir()
    tenant = str(user.get("tenant_id") or "default")
    current_owner = str(user.get("workspace_id", user.get("username", ""))).strip().lower()

    if target_owner and target_owner != current_owner:
        if not _is_admin(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator privileges required to access another user's Filebox",
            )
        owner = target_owner.strip().lower()
    else:
        owner = current_owner

    return storage_dir / "filebox_data" / tenant / owner


def _get_filebox(user: dict[str, Any], target_owner: Optional[str] = None) -> Filebox:
    """Return a Filebox instance for the target user, bootstrapping if needed."""
    root = _filebox_root_for(user, target_owner)
    actor = str(user.get("username", "agent"))
    if not root.exists() or not (root / "filebox.yaml").exists():
        owner_name = target_owner or str(user.get("username", "agent"))
        bootstrap.init(root, agent_id=owner_name)
    return Filebox(root, actor=actor)


# ── Request / Response models ──────────────────────────────────────────────

class WriteFileRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., max_length=10_485_760)  # 10 MB text
    reason: str = ""
    target_owner: Optional[str] = None


class WriteFileBase64Request(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    content_base64: str = Field(..., min_length=1, max_length=67_108_864)
    reason: str = ""
    target_owner: Optional[str] = None


class CreateDirRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    target_owner: Optional[str] = None


class MoveRequest(BaseModel):
    src: str = Field(..., min_length=1, max_length=512)
    dst: str = Field(..., min_length=1, max_length=512)
    reason: str = ""
    target_owner: Optional[str] = None


class DeleteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    reason: str = ""
    target_owner: Optional[str] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=256)
    path: str = ""
    limit: int = Field(default=50, ge=1, le=200)
    target_owner: Optional[str] = None


class MigrateRequest(BaseModel):
    source_dir: Optional[str] = None
    migrate_legacy_storage: bool = True
    dry_run: bool = False
    target_owner: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/users")
async def list_available_users(user: dict = Depends(get_current_user)):
    """List available user fileboxes in the current tenant for multi-user navigation."""
    storage_dir = _resolve_storage_dir()
    tenant = str(user.get("tenant_id") or "default")
    current_user = str(user.get("workspace_id", user.get("username", ""))).strip().lower()
    is_admin = _is_admin(user)

    tenant_dir = storage_dir / "filebox_data" / tenant
    discovered = []

    if is_admin and tenant_dir.exists():
        for item in sorted(tenant_dir.iterdir()):
            if item.is_dir():
                manifest = item / "filebox.yaml"
                discovered.append({
                    "username": item.name,
                    "is_current": item.name == current_user,
                    "initialized": manifest.exists(),
                    "path": str(item),
                })

    if not discovered:
        discovered.append({
            "username": current_user,
            "is_current": True,
            "initialized": (tenant_dir / current_user / "filebox.yaml").exists(),
            "path": str(tenant_dir / current_user),
        })

    return {
        "current_user": current_user,
        "tenant": tenant,
        "is_admin": is_admin,
        "users": discovered,
    }


@router.get("/tree")
async def get_tree(
    path: str = "",
    depth: int = Query(default=4, ge=1, le=10),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Return a recursive file tree for the Filebox."""
    fb = _get_filebox(user, target_owner=owner)
    try:
        tree = fb.tree(path, depth=depth)
        return tree.model_dump()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Path not found")


@router.get("/list")
async def list_dir(
    path: str = "",
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """List immediate children of a directory."""
    fb = _get_filebox(user, target_owner=owner)
    try:
        return {"items": fb.list(path)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Path not found")
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail="Not a directory")


@router.get("/read")
async def read_file(
    path: str = Query(..., min_length=1),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Read a file's content (returned as UTF-8 text or base64 for binary)."""
    fb = _get_filebox(user, target_owner=owner)
    try:
        content = fb.read(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail="Path is a directory")

    # Determine mime type
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "application/octet-stream"

    try:
        text = content.decode("utf-8")
        return {
            "path": path,
            "content": text,
            "encoding": "utf-8",
            "size": len(content),
            "mime": mime,
        }
    except UnicodeDecodeError:
        return {
            "path": path,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
            "size": len(content),
            "mime": mime,
        }


@router.get("/raw")
async def raw_file(
    path: str = Query(..., min_length=1),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Download or stream raw file bytes."""
    fb = _get_filebox(user, target_owner=owner)
    try:
        content = fb.read(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail="Path is a directory")

    mime, _ = mimetypes.guess_type(path)
    return Response(content=content, media_type=mime or "application/octet-stream")


@router.get("/stat")
async def stat_file(
    path: str = Query(..., min_length=1),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Return metadata for a file or directory."""
    fb = _get_filebox(user, target_owner=owner)
    try:
        return fb.stat(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/write")
async def write_file(req: WriteFileRequest, user: dict = Depends(get_current_user)):
    """Write text content to a file."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        fb.write(req.path, req.content, reason=req.reason or f"Web UI edit by {user.get('username')}")
        try:
            await event_bus.emit("filebox_changed", {"action": "write", "path": req.path, "owner": req.target_owner or user.get("username")})
        except Exception:
            pass
        return {"status": "ok", "path": req.path}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/write-binary")
async def write_binary(req: WriteFileBase64Request, user: dict = Depends(get_current_user)):
    """Write base64-encoded binary content to a file."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        content = base64.b64decode(req.content_base64, validate=True)
        fb.write(req.path, content, reason=req.reason or f"Web UI upload by {user.get('username')}")
        try:
            await event_bus.emit("filebox_changed", {"action": "write_binary", "path": req.path, "owner": req.target_owner or user.get("username")})
        except Exception:
            pass
        return {"status": "ok", "path": req.path, "size": len(content)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/mkdir")
async def make_dir(req: CreateDirRequest, user: dict = Depends(get_current_user)):
    """Create a new directory."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        fb.mkdir(req.path, reason=f"Web UI mkdir by {user.get('username')}")
        try:
            await event_bus.emit("filebox_changed", {"action": "mkdir", "path": req.path, "owner": req.target_owner or user.get("username")})
        except Exception:
            pass
        return {"status": "ok", "path": req.path}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/move")
async def move_file(req: MoveRequest, user: dict = Depends(get_current_user)):
    """Move or rename a file/directory."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        fb.move(req.src, req.dst, reason=req.reason or f"Web UI move by {user.get('username')}")
        try:
            await event_bus.emit("filebox_changed", {"action": "move", "src": req.src, "dst": req.dst, "owner": req.target_owner or user.get("username")})
        except Exception:
            pass
        return {"status": "ok", "src": req.src, "dst": req.dst}
    except (PermissionError, FileNotFoundError) as e:
        code = 403 if isinstance(e, PermissionError) else 404
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/delete")
async def delete_file(req: DeleteRequest, user: dict = Depends(get_current_user)):
    """Delete a file or directory."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        deleted = fb.delete(req.path, reason=req.reason or f"Web UI delete by {user.get('username')}")
        if not deleted:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            await event_bus.emit("filebox_changed", {"action": "delete", "path": req.path, "owner": req.target_owner or user.get("username")})
        except Exception:
            pass
        return {"status": "deleted", "path": req.path}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/search")
async def search_files(req: SearchRequest, user: dict = Depends(get_current_user)):
    """Full-text and indexed search across the Filebox."""
    fb = _get_filebox(user, target_owner=req.target_owner)
    try:
        results = fb.search(req.query, path=req.path, limit=req.limit)
        return {"query": req.query, "results": results, "total": len(results)}
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail="Search path is not a directory")


@router.post("/index")
async def build_search_index(
    force: bool = Query(default=False),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Rebuild SQLite FTS5 search index."""
    fb = _get_filebox(user, target_owner=owner)
    result = fb.build_index(force=force)
    return {"status": "ok", "result": result}


@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Return recent audit events."""
    fb = _get_filebox(user, target_owner=owner)
    events = fb.audit.recent(limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/status")
async def filebox_status(
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Return Filebox status and verification results."""
    fb = _get_filebox(user, target_owner=owner)
    root = fb.root
    verification = bootstrap.verify(root)

    total_files = 0
    total_size = 0
    for f in root.rglob("*"):
        if f.is_file():
            total_files += 1
            total_size += f.stat().st_size

    return {
        "initialized": True,
        "root": str(root),
        "owner": owner or str(user.get("workspace_id", user.get("username", ""))).strip().lower(),
        "valid": verification["valid"],
        "issues": verification["issues"],
        "total_files": total_files,
        "total_size": total_size,
        "categories": list(fb.CATEGORIES),
    }


@router.post("/init")
async def init_filebox(
    owner: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Bootstrap a fresh Filebox for the current user or specified owner."""
    root = _filebox_root_for(user, target_owner=owner)
    target_owner = owner or str(user.get("username", "agent"))
    bootstrap.init(root, agent_id=target_owner)
    return {"status": "initialized", "root": str(root), "owner": target_owner}


@router.post("/migrate")
async def run_migration(
    req: MigrateRequest,
    user: dict = Depends(get_current_user),
):
    """Execute migration from a legacy sandbox directory or legacy platform storage."""
    migrator = FileboxMigrator()
    target_owner = req.target_owner or str(user.get("workspace_id", user.get("username", ""))).strip().lower()
    target_root = _filebox_root_for(user, target_owner=target_owner)
    tenant = str(user.get("tenant_id") or "default")

    results: list[dict[str, Any]] = []

    if req.source_dir:
        report = migrator.migrate_directory(
            source_dir=req.source_dir,
            target_dir=target_root,
            agent_id=target_owner,
            dry_run=req.dry_run,
        )
        results.append(report.to_dict())

    if req.migrate_legacy_storage:
        reports = migrator.migrate_legacy_storage(
            tenant_id=tenant,
            owner_id=target_owner,
            dry_run=req.dry_run,
        )
        results.extend([r.to_dict() for r in reports])

    return {
        "status": "completed",
        "target": str(target_root),
        "owner": target_owner,
        "reports": results,
    }
