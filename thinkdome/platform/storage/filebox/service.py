"""FileBox service: encrypted files plus ORM retention metadata."""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
import uuid
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from thinkdome.core.config import get_settings, get_workspace_root
from thinkdome.platform.storage.filebox.models import FileBox, FileBoxVolume
from thinkdome.platform.storage.utils import safe_filename
from thinkdome.platform.storage.workspace_crypto import workspace_cipher
from .container import BoxContainer

DEFAULT_FOLDERS = ("workspace", "uploads", "artifacts", "cache", "tmp", "logs")
DEFAULT_QUOTA_BYTES = 10 * 1024 * 1024 * 1024
_NAMESPACE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
logger = logging.getLogger(__name__)


class FileBoxService:
    _quota_locks: dict[tuple[str, str], threading.Lock] = {}
    _quota_locks_guard = threading.Lock()

    @classmethod
    def _quota_lock(cls, tenant_id: str, owner_id: str) -> threading.Lock:
        key = (tenant_id, owner_id)
        with cls._quota_locks_guard:
            return cls._quota_locks.setdefault(key, threading.Lock())

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        storage_dir = Path(self.settings.FILE_STORAGE_DIR)
        if not storage_dir.is_absolute():
            storage_dir = get_workspace_root() / storage_dir
        self.root = storage_dir / "filebox"
        quota_mb = int(getattr(self.settings, "FILEBOX_DEFAULT_QUOTA_MB", 10240))
        try:
            from thinkdome.apps.sandbox.models import SystemSetting
            record = SystemSetting.query().filter(key="filebox_default_quota_mb").first()
            if record and str(record.value).isdigit():
                quota_mb = int(record.value)
        except Exception:
            pass
        self.default_quota_bytes = quota_mb * 1024 * 1024
        self.root.mkdir(parents=True, exist_ok=True)
        # FileBox models are loaded by the API router after the kernel's
        # initial schema pass. Ensure the virtual-volume table exists before
        # the first volume lookup (ORM-managed; no raw SQL).
        from thinkdome.core.kernel.kernel import Kernel
        from thinkdome.core.orm.orm import Base
        kernel = Kernel.current()
        if not kernel.initialized:
            kernel.initialize()
        Base.metadata.create_all(kernel.db_engine)

    @staticmethod
    def _validate_namespace(tenant_id: str, owner_id: str) -> None:
        """Reject path-unsafe tenant/user identifiers before filesystem use."""
        for label, value in (("tenant_id", tenant_id), ("owner_id", owner_id)):
            if not isinstance(value, str) or not _NAMESPACE_COMPONENT.fullmatch(value):
                raise ValueError(
                    f"{label} must be a single alphanumeric namespace component"
                )

    def ensure_layout(self, *, tenant_id: str, owner_id: str) -> dict[str, Path]:
        """Create the standard semantic folders for one owner namespace."""
        self._validate_namespace(tenant_id, owner_id)
        owner_root = self.root / tenant_id / owner_id
        volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
        if volume is not None:
            current_root = Path(volume.root_path)
            container_file = current_root.parent / (current_root.name[:-5] if current_root.name.endswith('.data') else current_root.name)
            if not container_file.exists():
                logger.error("FileBox container missing: tenant=%s owner=%s path=%s; locking and recreating", tenant_id, owner_id, container_file)
                volume._values["status"] = "locked"
                volume.save()
                for old_meta in FileBox.query().filter(tenant_id=tenant_id, owner_id=owner_id, status="active").all():
                    old_meta._values.update(status="expired", deleted_at=datetime.now(timezone.utc).isoformat())
                    old_meta.save()
                volume = None
        if volume is None:
            # A .box directory is the stable virtual-disk container. Its
            # contents remain encrypted per file, while the container name is
            # opaque and unique to this tenant/user volume.
            volume_id = uuid.uuid4().hex
            container_file = owner_root / f"{volume_id}.box"
            box_root = owner_root / f"{volume_id}.box.data"
            container_file.parent.mkdir(parents=True, exist_ok=True)
            BoxContainer(container_file, f"{tenant_id}:{owner_id}")._save({"format": "thinkdome-box-v1", "files": {}})
            FileBoxVolume(
                tenant_id=tenant_id, owner_id=owner_id, volume_name="default",
                container_format="thinkdome-box-v1", root_path=str(box_root),
                encryption="fernet",
                key_scope=f"{tenant_id}:{owner_id}", quota_bytes=self.default_quota_bytes,
                used_bytes=0, created_at=datetime.now(timezone.utc).isoformat(),
            ).save()
            owner_root = box_root
        else:
            owner_root = Path(volume.root_path)
            if owner_root.name.endswith(".box.data"):
                container_file = owner_root.parent / owner_root.name[:-5]
                if not container_file.exists() or not container_file.read_bytes().startswith(b"TDBOX1:"):
                    BoxContainer(container_file, f"{tenant_id}:{owner_id}")._save({"format": "thinkdome-box-v1", "files": {}})
            if not owner_root.name.endswith(".box") and not owner_root.name.endswith(".box.data"):
                legacy_root = owner_root
                owner_root = legacy_root / f"{uuid.uuid4().hex}.box"
                owner_root.mkdir(parents=True, exist_ok=True)
                for folder_name in DEFAULT_FOLDERS:
                    source = legacy_root / folder_name
                    target = owner_root / folder_name
                    if source.exists() and not target.exists():
                        shutil.move(str(source), str(target))
                volume._values["root_path"] = str(owner_root)
                volume.save()
            elif owner_root.is_dir() and owner_root.name.endswith(".box"):
                # Convert early directory-style containers to an explicit
                # .box image marker plus a private data directory.
                container_file = owner_root.with_suffix("")
                container_file = container_file.with_name(container_file.name + ".box")
                data_root = owner_root.with_name(owner_root.name + ".data")
                if not data_root.exists():
                    owner_root.rename(data_root)
                BoxContainer(container_file, f"{tenant_id}:{owner_id}")._save({"format": "thinkdome-box-v1", "files": {}})
                owner_root = data_root
                volume._values.update(root_path=str(owner_root))
                volume.save()
        if not owner_root.name.endswith(".box.data"):
            owner_root.mkdir(parents=True, exist_ok=True)
        folders = {}
        for name in DEFAULT_FOLDERS:
            path = owner_root / name
            # Folder names are logical entries inside the encrypted .box
            # container; no plaintext sidecar directory is required.
            if not owner_root.name.endswith(".box.data"):
                path.mkdir(parents=True, exist_ok=True)
            folders[name] = path
        return folders

    def get_volume(self, *, tenant_id: str, owner_id: str) -> FileBoxVolume | None:
        return FileBoxVolume.query().filter(
            tenant_id=tenant_id, owner_id=owner_id, volume_name="default", status="active"
        ).first()

    def _container(self, volume: FileBoxVolume) -> BoxContainer:
        root = Path(volume.root_path)
        path = root.parent / (root.name[:-5] if root.name.endswith('.data') else root.name)
        if not path.name.endswith('.box'):
            path = path.with_name(path.name + '.box')
        return BoxContainer(path, f"{volume.tenant_id}:{volume.owner_id}")

    def create(self, *, tenant_id: str, owner_id: str, filename: str, content: bytes,
               ttl_seconds: int | None = None, permanent: bool = False,
               folder: str = "workspace", override: bool = False,
               conflict: str = "version") -> FileBox:
        if not tenant_id or not owner_id:
            raise PermissionError("Tenant and authenticated owner are required.")
        if not permanent and (ttl_seconds is None or ttl_seconds <= 0):
            raise ValueError("Temporary FileBox entries require a positive ttl_seconds.")
        safe_name = safe_filename(filename)
        if conflict not in {"version", "error", "override"}:
            raise ValueError("conflict must be one of: version, error, override")
        if override:
            conflict = "override"
        if not re.fullmatch(r"[A-Za-z0-9._-]+", folder or "") or folder not in DEFAULT_FOLDERS:
            raise ValueError(f"folder must be one of: {', '.join(DEFAULT_FOLDERS)}")
        folders = self.ensure_layout(tenant_id=tenant_id, owner_id=owner_id)
        volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
        if volume is None:
            raise RuntimeError("FileBox volume could not be initialized")
        # A filename is unique inside one owner's tenant namespace. Never
        # silently overwrite or create ambiguous active entries.
        for existing in FileBox.query().filter(
            tenant_id=tenant_id, owner_id=owner_id, filename=safe_name, status="active"
        ).all():
            if not existing.expires_at or existing.expires_at > time.time():
                if conflict == "override":
                    self.delete(existing.id, tenant_id=tenant_id, owner_id=owner_id)
                    continue
                if conflict == "error":
                    raise FileExistsError(
                        f"FileBox filename '{safe_name}' already exists for this owner."
                    )
                stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
                index = 1
                while FileBox.query().filter(
                    tenant_id=tenant_id, owner_id=owner_id,
                    filename=f"{stem} ({index}){suffix}", status="active"
                ).first():
                    index += 1
                safe_name = f"{stem} ({index}){suffix}"
                break
            self._expire(existing)
        # Refresh after conflict handling because override/expiry may have
        # released bytes from the volume while this request was in progress.
        volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
        with self._quota_lock(tenant_id, owner_id):
            volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
            if volume is None:
                raise RuntimeError("FileBox volume could not be initialized")
            if int(volume.used_bytes or 0) + len(content) > int(volume.quota_bytes or self.default_quota_bytes):
                raise OSError("Storage quota exceeded: FileBox virtual volume quota exceeded")
            box_id = str(uuid.uuid4())
            path = Path(volume.root_path) / folder / safe_name
            self._container(volume).put(f"{folder}/{box_id}/{safe_name}", content)
            now = time.time()
            meta = FileBox(
                id=box_id,
                tenant_id=tenant_id,
                owner_id=owner_id,
                volume_id="default",
                filename=safe_name,
                folder=folder,
                storage_path=str(path),
                retention="permanent" if permanent else "temporary",
                expires_at=0.0 if permanent else now + int(ttl_seconds),
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            meta.save()
            volume._values["used_bytes"] = int(volume.used_bytes or 0) + len(content)
            volume.save()
            return meta

    def get(self, filebox_id: str, *, tenant_id: str, owner_id: str) -> FileBox | None:
        meta = FileBox.query().filter(id=filebox_id).first()
        if not meta or meta.status != "active" or meta.tenant_id != tenant_id or meta.owner_id != owner_id:
            return None
        if meta.expires_at and meta.expires_at <= time.time():
            self._expire(meta)
            return None
        return meta

    def read(self, filebox_id: str, *, tenant_id: str, owner_id: str) -> tuple[bytes, FileBox] | None:
        meta = self.get(filebox_id, tenant_id=tenant_id, owner_id=owner_id)
        if not meta:
            return None
        volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
        content = self._container(volume).get(f"{meta.folder}/{meta.id}/{meta.filename}") if volume else None
        return (content, meta) if content is not None else None

    def list(self, *, tenant_id: str, owner_id: str) -> list[FileBox]:
        """List only active FileBoxes owned by this tenant/user pair."""
        self.ensure_layout(tenant_id=tenant_id, owner_id=owner_id)
        result = []
        for meta in FileBox.query().filter(tenant_id=tenant_id, owner_id=owner_id, status="active").all():
            if meta.expires_at and meta.expires_at <= time.time():
                self._expire(meta)
            else:
                result.append(meta)
        return result

    def exists(self, filebox_id: str, *, tenant_id: str, owner_id: str) -> bool:
        return self.get(filebox_id, tenant_id=tenant_id, owner_id=owner_id) is not None

    def delete(self, filebox_id: str, *, tenant_id: str, owner_id: str) -> bool:
        meta = self.get(filebox_id, tenant_id=tenant_id, owner_id=owner_id)
        if not meta:
            return False
        volume = self.get_volume(tenant_id=tenant_id, owner_id=owner_id)
        if volume:
            self._container(volume).remove(f"{meta.folder}/{meta.id}/{meta.filename}")
        meta._values.update(status="deleted", deleted_at=datetime.now(timezone.utc).isoformat())
        meta.save()
        self._release_bytes(meta)
        return True

    def renew(self, filebox_id: str, *, tenant_id: str, owner_id: str, ttl_seconds: int) -> FileBox | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        meta = self.get(filebox_id, tenant_id=tenant_id, owner_id=owner_id)
        if not meta:
            return None
        meta._values.update(retention="temporary", expires_at=time.time() + ttl_seconds)
        meta.save()
        return meta

    def _release_bytes(self, meta: FileBox) -> None:
        volume = self.get_volume(tenant_id=meta.tenant_id, owner_id=meta.owner_id)
        if volume:
            volume._values["used_bytes"] = max(0, int(volume.used_bytes or 0) - int(meta.size_bytes or 0))
            volume.save()

    def make_permanent(self, filebox_id: str, *, tenant_id: str, owner_id: str) -> FileBox | None:
        meta = self.get(filebox_id, tenant_id=tenant_id, owner_id=owner_id)
        if not meta:
            return None
        meta._values.update(retention="permanent", expires_at=0.0)
        meta.save()
        return meta

    def copy(self, filebox_id: str, *, tenant_id: str, owner_id: str, filename: str) -> FileBox | None:
        result = self.read(filebox_id, tenant_id=tenant_id, owner_id=owner_id)
        if not result:
            return None
        content, source = result
        permanent = source.retention == "permanent"
        ttl = None if permanent else max(1, int(source.expires_at - time.time()))
        return self.create(
            tenant_id=tenant_id, owner_id=owner_id, filename=filename,
            content=content, ttl_seconds=ttl, permanent=permanent,
            folder=source.folder,
        )

    def _expire(self, meta: FileBox) -> None:
        volume = self.get_volume(tenant_id=meta.tenant_id, owner_id=meta.owner_id)
        if volume:
            self._container(volume).remove(f"{meta.folder}/{meta.id}/{meta.filename}")
        meta._values.update(status="expired", deleted_at=datetime.now(timezone.utc).isoformat())
        meta.save()
        self._release_bytes(meta)

    def reap_expired(self, limit: int = 100) -> int:
        count = 0
        for meta in FileBox.query().filter(status="active").all():
            if count >= limit:
                break
            if meta.expires_at and meta.expires_at <= time.time():
                self._expire(meta)
                count += 1
        return count
