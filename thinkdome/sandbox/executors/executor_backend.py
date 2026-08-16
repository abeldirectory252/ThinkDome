"""Abstract executor backend interface for ThinkDome.

Enables pluggable code execution strategies (e.g. Docker, Kubernetes, Subprocess).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SandboxHandle:
    """Opaque handler referencing an active sandbox."""
    sandbox_id: str
    container_id: str  # Docker container ID or Kubernetes pod name
    backend_type: str  # "docker" | "kubernetes"
    ip_address: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class ExecutionResult:
    """Result of code or command execution within a sandbox."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: float


@dataclass
class BackendHealth:
    """Health status details of an execution backend."""
    status: str  # "healthy" | "unhealthy"
    details: Dict[str, Any]


class ExecutorBackend(ABC):
    """Abstract base class for all execution backends."""

    @abstractmethod
    async def create_sandbox(
        self,
        sandbox_id: str,
        memory_mb: int,
        cpu_cores: float,
        network_enabled: bool,
        gpu_count: int = 0,
    ) -> SandboxHandle:
        """Create and start a new isolated sandbox environment."""
        pass

    @abstractmethod
    async def execute_in_sandbox(
        self,
        handle: SandboxHandle,
        command: list[str],
        user: str = "sandboxuser",
        env_vars: Optional[Dict[str, str]] = None,
        timeout_ms: int = 10000,
    ) -> ExecutionResult:
        """Execute a command inside the specified sandbox."""
        pass

    @abstractmethod
    async def destroy_sandbox(self, handle: SandboxHandle) -> None:
        """Permanently stop and delete the sandbox."""
        pass

    @abstractmethod
    async def health_check(self) -> BackendHealth:
        """Perform backend connectivity checks."""
        pass
