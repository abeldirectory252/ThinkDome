"""Abstract base executor interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ExecRequest:
    """Unified execution request for all backends."""
    code: str
    language: str = "python"
    stdin: Optional[str] = None
    timeout_ms: int = 5000
    files: dict[str, bytes] = field(default_factory=dict)  # path -> content
    memory_limit_mb: Optional[int] = None
    cpu_time_limit_sec: int = 5
    max_output_bytes: int = 1_048_576
    security_profile: str = "HIGH_SECURITY"
    env_vars: Optional[dict[str, str]] = None
    caller_role: str = "LLM"         # "LLM" | "ADMIN" — determines resource limits & network
    allow_network: bool = False      # Explicit network access flag
    cpu_cores: Optional[float] = None


@dataclass
class ExecResult:
    """Unified execution result from all backends."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: float = 0.0
    output_files: dict[str, bytes] = field(default_factory=dict)  # path -> content


class BaseExecutor(ABC):
    """Abstract executor interface."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the executor (pull images, etc.)."""
        ...

    @abstractmethod
    async def execute(self, request: ExecRequest) -> ExecResult:
        """Execute code and return results."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup resources."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if executor is ready."""
        ...
