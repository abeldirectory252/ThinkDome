"""Narrow node-orchestrator boundary used by the control plane."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional, Protocol

from pydantic import BaseModel, Field


class OrchestratorOperation(str, Enum):
    CREATE = "create"
    EXECUTE = "execute"
    PAUSE = "pause"
    RESUME = "resume"
    TERMINATE = "terminate"


class OrchestratorAuthorization(BaseModel):
    """Operation-scoped authorization context signed by the control plane."""

    organization_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    sandbox_id: str = Field(min_length=1)
    operation: OrchestratorOperation
    request_id: str = Field(min_length=1)
    expires_at: datetime

    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)


class OrchestratorSandboxRequest(BaseModel):
    """Backend-neutral sandbox request sent to an execution node."""

    authorization: OrchestratorAuthorization
    image_ref: str = Field(min_length=1)
    cpu_millis: int = Field(gt=0)
    memory_bytes: int = Field(gt=0)
    pids: int = Field(gt=0)
    network_policy_id: str = Field(default="blocked", min_length=1)


class OrchestratorExecutionRequest(BaseModel):
    """Execution payload; file contents remain bounded by the API policy."""

    authorization: OrchestratorAuthorization
    code: str = Field(min_length=1, max_length=100_000)
    language: str = Field(default="python", min_length=1, max_length=32)
    stdin: Optional[str] = Field(default=None, max_length=1_000_000)
    environment: Mapping[str, str] = Field(default_factory=dict)


class OrchestratorResult(BaseModel):
    """Normalized node result returned to the control plane."""

    request_id: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error_code: Optional[str] = None


class NodeOrchestrator(Protocol):
    """Transport-neutral interface implemented by a node agent client."""

    async def create_sandbox(self, request: OrchestratorSandboxRequest) -> None:
        ...

    async def execute(self, request: OrchestratorExecutionRequest) -> OrchestratorResult:
        ...

    async def pause_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        ...

    async def resume_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        ...

    async def terminate_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        ...

