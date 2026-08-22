"""Tenant/project quota admission checks."""

from __future__ import annotations

from dataclasses import dataclass

from thinkdome.control_plane.contracts import SandboxPlacementRequest


class QuotaExceededError(ValueError):
    """A project cannot admit the requested sandbox."""


@dataclass(frozen=True)
class ProjectUsage:
    sandboxes: int = 0
    cpu_millis: int = 0
    memory_bytes: int = 0


@dataclass(frozen=True)
class ProjectQuota:
    max_sandboxes: int = 10
    max_cpu_millis: int = 4000
    max_memory_bytes: int = 8_589_934_592

    def check(self, request: SandboxPlacementRequest, usage: ProjectUsage) -> None:
        if usage.sandboxes + 1 > self.max_sandboxes:
            raise QuotaExceededError("project sandbox quota exceeded")
        if usage.cpu_millis + request.cpu_millis > self.max_cpu_millis:
            raise QuotaExceededError("project CPU quota exceeded")
        if usage.memory_bytes + request.memory_bytes > self.max_memory_bytes:
            raise QuotaExceededError("project memory quota exceeded")
