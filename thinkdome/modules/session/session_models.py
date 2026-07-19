"""Session schemas."""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    language: str = Field(default="python")
    timeout_ms: int = Field(default=30000, ge=1000, le=300000)


class SessionInfo(BaseModel):
    session_id: str
    language: str
    status: str  # "active" | "closed"
    created_at: datetime
    last_activity: datetime
    execution_count: int = 0


class SessionExecRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100_000)
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    last_line_interactive: bool = False


class SessionExecResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: float = 0.0
    execution_index: int = 0
