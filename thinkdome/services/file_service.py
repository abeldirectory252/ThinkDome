"""File management service."""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from thinkdome.core.config import Settings
from thinkdome.models.files import FileMetadata
from thinkdome.utils.files import compute_sha256, safe_filename

logger = logging.getLogger(__name__)


class FileService:
    """Manages uploaded and generated files."""

    def __init__(self, settings: Settings) -> None:
        self.storage_dir = Path(settings.FILE_STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        self._metadata: dict[str, FileMetadata] = {}
        logger.info(f"FileService initialized: {self.storage_dir}")

    def upload(self, filename: str, content: bytes, content_type: Optional[str] = None) -> FileMetadata:
        """Store an uploaded file and return metadata."""
        if len(content) > self.max_size:
            raise ValueError(
                f"File too large: {len(content)} bytes (max {self.max_size})"
            )

        file_id = str(uuid.uuid4())
        safe_name = safe_filename(filename)
        file_path = self.storage_dir / file_id / safe_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        sha = compute_sha256(content)
        now = datetime.now(timezone.utc)

        meta = FileMetadata(
            file_id=file_id,
            filename=safe_name,
            size_bytes=len(content),
            content_type=content_type,
            sha256=sha,
            created_at=now,
        )
        self._metadata[file_id] = meta
        logger.info(f"File uploaded: {file_id} ({safe_name}, {len(content)} bytes)")
        return meta

    def get_metadata(self, file_id: str) -> Optional[FileMetadata]:
        return self._metadata.get(file_id)

    def get_content(self, file_id: str) -> Optional[tuple[bytes, FileMetadata]]:
        meta = self._metadata.get(file_id)
        if not meta:
            return None
        file_path = self.storage_dir / file_id / meta.filename
        if not file_path.exists():
            return None
        return file_path.read_bytes(), meta

    def list_files(self) -> list[FileMetadata]:
        return list(self._metadata.values())

    def delete(self, file_id: str, hard: bool = True) -> bool:
        meta = self._metadata.pop(file_id, None)
        if not meta:
            return False
        if hard:
            dir_path = self.storage_dir / file_id
            if dir_path.exists():
                shutil.rmtree(dir_path)
        return True

    def update(self, file_id: str, content: bytes) -> Optional[FileMetadata]:
        meta = self._metadata.get(file_id)
        if not meta:
            return None
        file_path = self.storage_dir / file_id / meta.filename
        file_path.write_bytes(content)
        meta.size_bytes = len(content)
        meta.sha256 = compute_sha256(content)
        meta.updated_at = datetime.now(timezone.utc)
        return meta

    def copy_file(self, file_id: str, new_path: str) -> Optional[FileMetadata]:
        result = self.get_content(file_id)
        if not result:
            return None
        content, old_meta = result
        return self.upload(new_path, content, old_meta.content_type)

    def move_file(self, file_id: str, new_path: str) -> Optional[FileMetadata]:
        new_meta = self.copy_file(file_id, new_path)
        if new_meta:
            self.delete(file_id)
        return new_meta

    def get_file_path(self, file_id: str) -> Optional[Path]:
        """Return the actual filesystem path for a stored file."""
        meta = self._metadata.get(file_id)
        if not meta:
            return None
        p = self.storage_dir / file_id / meta.filename
        return p if p.exists() else None
