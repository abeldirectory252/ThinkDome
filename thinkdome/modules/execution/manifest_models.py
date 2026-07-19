"""Sandbox manifest defining workspace initialization contract (OpenAI style)."""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class GitRepositoryImport(BaseModel):
    """Git repository to clone into the sandbox workspace upon startup."""
    url: str = Field(..., description="Repository HTTPS URL")
    branch: Optional[str] = Field(None, description="Target branch or commit hash")
    destination: str = Field(".", description="Relative path in workspace where it should be cloned")


class MountSpec(BaseModel):
    """Volume mount specs inside the sandbox."""
    host_path: Optional[str] = Field(None, description="Host source path")
    container_path: str = Field(..., description="Target mount path inside sandbox")
    mode: str = Field("ro", description="rw (read-write) or ro (read-only)")
    type: str = Field("tmpfs", description="tmpfs | bind")


class CredentialExclusions(BaseModel):
    """Paths and env variables blacklisted from sandbox command access."""
    blocked_paths: List[str] = Field(default_factory=list, description="File paths denied for reading")
    blocked_env_vars: List[str] = Field(default_factory=list, description="Env variables to unset/remove")


class SandboxManifest(BaseModel):
    """Workspace manifest defining sandbox startup environment presets."""
    files: Dict[str, str] = Field(default_factory=dict, description="Pre-seeded workspace files (path -> base64/content)")
    git_repositories: List[GitRepositoryImport] = Field(default_factory=list, description="Repos to clone on start")
    mounts: List[MountSpec] = Field(default_factory=list, description="Pre-provisioned mounts")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables to set")
    credentials: CredentialExclusions = Field(default_factory=CredentialExclusions, description="Credential protection settings")
