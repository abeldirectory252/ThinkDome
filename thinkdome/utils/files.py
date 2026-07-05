"""File encoding/decoding utilities."""

import base64
import hashlib
from pathlib import Path


def encode_file_base64(filepath: Path) -> str:
    """Read a file and return its base64-encoded content."""
    return base64.b64encode(filepath.read_bytes()).decode("utf-8")


def decode_base64(data: str) -> bytes:
    """Decode base64 string to bytes."""
    return base64.b64decode(data)


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    """Sanitize a filename to prevent directory traversal."""
    p = Path(name)
    # Strip any leading path separators or parent references
    parts = [part for part in p.parts if part not in ("..", ".", "/", "\\")]
    if not parts:
        return "unnamed"
    return str(Path(*parts))
