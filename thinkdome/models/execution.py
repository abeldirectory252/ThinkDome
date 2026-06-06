"""Execution request/response schemas."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class FileInput(BaseModel):
    """File to inject into the execution environment."""
    path: str = Field(..., description="Filename or relative path inside workspace")
    content_base64: Optional[str] = Field(None, description="Base64-encoded file content")
    file_id: Optional[str] = Field(None, description="Reference to previously uploaded file")


class ExecuteRequest(BaseModel):
    """Single code execution request."""
    code: str = Field(..., min_length=1, max_length=100_000, description="Code to execute")
    language: str = Field(default="python", description="Language identifier")
    stdin: Optional[str] = Field(None, description="Standard input to provide")
    timeout_ms: int = Field(default=5000, ge=100, le=120000, description="Execution timeout in ms")
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
    caller_role: str = Field(
        default="LLM",
        description="Role of the caller: LLM (limited resources) or ADMIN (full resources)"
    )
    allow_network: bool = Field(
        default=False,
        description="Whether to allow network access (only effective for ADMIN callers)"
    )
    memory_limit_mb: Optional[int] = Field(None, description="Custom memory limit in MB")
    cpu_cores: Optional[float] = Field(None, description="Custom CPU cores limit")


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


class BatchExecuteRequest(BaseModel):
    """Execute multiple code blocks sequentially."""
    executions: list[ExecuteRequest] = Field(..., min_length=1, max_length=50)


class BatchExecuteResponse(BaseModel):
    """Batch execution results."""
    results: list[ExecuteResponse]
    total_duration_ms: float
