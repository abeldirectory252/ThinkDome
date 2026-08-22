"""FileBox: tenant-scoped files with explicit retention metadata."""

from .models import FileBox, FileBoxVolume
from .service import FileBoxService

__all__ = ["FileBox", "FileBoxVolume", "FileBoxService"]
