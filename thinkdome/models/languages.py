"""Language and runtime schemas."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class LanguageInfo(BaseModel):
    name: str
    version: str
    status: str  # "available" | "coming_soon"
    extensions: list[str]


class PackageInfo(BaseModel):
    name: str
    version: str


class PackageInstallRequest(BaseModel):
    package_name: str = Field(..., max_length=128)
    version: Optional[str] = None


class RuntimeInfo(BaseModel):
    image: str
    language: str
    status: str  # "ready" | "pulling" | "unavailable"
    size_mb: Optional[float] = None
