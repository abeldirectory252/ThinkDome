"""Execution request/response schemas."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pathlib import PurePosixPath


class FileInput(BaseModel):
    """File to inject into the execution environment."""
    path: str = Field(..., description="Filename or relative path inside workspace")
    content_base64: Optional[str] = Field(None, description="Base64-encoded file content")
    file_id: Optional[str] = Field(None, description="Reference to previously uploaded file")

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """Only allow files below the sandbox workspace."""
        if not value or "\x00" in value:
            raise ValueError("file path must be non-empty and contain no NUL bytes")
        raw_parts = value.replace("\\", "/").split("/")
        if any(part in {"", ".", ".."} for part in raw_parts):
            raise ValueError("file path must be relative and cannot contain '.', '..', or empty segments")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("file path must be relative and cannot contain '.' or '..'")
        if len(value) > 512:
            raise ValueError("file path is too long")
        return value


class ExecuteRequest(BaseModel):
    """Single code execution request."""
    code: str = Field(..., min_length=1, max_length=100_000, description="Code to execute")
    language: str = Field(default="python", min_length=1, max_length=32, description="Language identifier")
    stdin: Optional[str] = Field(None, max_length=1_000_000, description="Standard input to provide")
    timeout_ms: int = Field(default=5000, ge=100, le=3600000, description="Execution timeout in ms")
    last_line_interactive: bool = Field(
        default=False,
        description="If true, auto-print the result of the last expression",
    )
    files: list[FileInput] = Field(default_factory=list, description="Files to inject")
    security_profile: str = Field(
        default="HIGH_SECURITY",
        description="Security profile for containment. Options: HIGH_SECURITY, ISOLATED, DEVELOPMENT"
    )
    env_vars: Optional[dict[str, str]] = Field(
        default=None,
        description="Custom environment variables to pass into the sandbox environment"
    )

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, value: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
        if value is None:
            return value
        blocked = {
            "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "PYTHONPATH",
            "PYTHONHOME", "RUBYLIB", "NODE_OPTIONS", "PERL5LIB",
        }
        if len(value) > 64:
            raise ValueError("at most 64 environment variables are allowed")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("environment variable names must be 1-128 characters")
            if key.upper() in blocked:
                raise ValueError(f"environment variable '{key}' is not allowed")
            if not isinstance(item, str) or len(item) > 8192:
                raise ValueError("environment variable values must be strings up to 8192 characters")
        return value
    caller_role: str = Field(
        default="LLM",
        description="Role of the caller: LLM (limited resources) or ADMIN (full resources)"
    )
    allow_network: bool = Field(
        default=False,
        description="Whether to allow network access (only effective for ADMIN callers)"
    )
    memory_limit_mb: Optional[int] = Field(None, gt=0, le=65_536, description="Custom memory limit in MB")
    cpu_cores: Optional[float] = Field(None, gt=0, le=64, description="Custom CPU cores limit")
    username: Optional[str] = Field(None, min_length=1, max_length=128, description="Username for user-specific workspace isolation")

    @field_validator("language")
    @classmethod
    def validate_language_identifier(cls, value: str) -> str:
        # Language is used to construct filenames inside executor sandboxes;
        # reject separators/control characters before it reaches a backend.
        if not value or not value.isascii() or not all(ch.isalnum() or ch in "_-+" for ch in value):
            raise ValueError("language must be a simple identifier")
        return value.lower()


class FileOutput(BaseModel):
    """File generated during execution."""
    path: str
    content_base64: str
    size_bytes: int


class ExecuteResponse(BaseModel):
    """Execution result."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: float = 0.0
    files: list[FileOutput] = Field(default_factory=list)
    session_id: Optional[str] = None
    error_code: Optional[str] = None


class BatchExecuteRequest(BaseModel):
    """Execute multiple code blocks sequentially."""
    executions: list[ExecuteRequest] = Field(..., min_length=1, max_length=50)


class BatchExecuteResponse(BaseModel):
    """Batch execution results."""
    results: list[ExecuteResponse]
    total_duration_ms: float
