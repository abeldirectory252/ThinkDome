"""Docker network attachment policy for sandbox containers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


class NetworkIsolationError(RuntimeError):
    """Raised when a sandbox cannot be attached to an approved network."""


@dataclass(frozen=True)
class DockerNetworkAttachment:
    mode: str
    environment: dict[str, str]


class DockerSandboxPolicy:
    """Resolve an approved Docker network; never silently fall back to bridge."""

    PROXY_NETWORK = "thinkbox-egress"
    PROXY_NETWORK_LABEL = "thinkdome.network"
    PROXY_NETWORK_ROLE = "egress-proxy"
    PROXY_HOST = "thinkbox-proxy"
    PROXY_PORT = 3128
    SANDBOX_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def __init__(self, docker_client: Any) -> None:
        self.client = docker_client

    def attachment(self, network_enabled: bool) -> DockerNetworkAttachment:
        if not network_enabled:
            return DockerNetworkAttachment(mode="none", environment={})

        try:
            networks = self.client.networks.list(names=[self.PROXY_NETWORK])
        except Exception as exc:
            raise NetworkIsolationError(
                f"Unable to verify approved egress network '{self.PROXY_NETWORK}'"
            ) from exc
        if not networks:
            raise NetworkIsolationError(
                f"Approved egress network '{self.PROXY_NETWORK}' is unavailable"
            )
        if len(networks) != 1:
            raise NetworkIsolationError(
                f"Approved egress network '{self.PROXY_NETWORK}' has an ambiguous identity"
            )
        network = networks[0]
        attrs = getattr(network, "attrs", {}) or {}
        if attrs.get("Driver") != "bridge":
            raise NetworkIsolationError("Approved egress network must use the bridge driver")
        if not attrs.get("Internal", False):
            raise NetworkIsolationError("Approved egress network must be Docker-internal")
        labels = attrs.get("Labels") or {}
        if labels.get(self.PROXY_NETWORK_LABEL) != self.PROXY_NETWORK_ROLE:
            raise NetworkIsolationError("Approved egress network is missing the required security label")

        return DockerNetworkAttachment(
            mode=self.PROXY_NETWORK,
            environment={
                "HTTP_PROXY": f"http://{self.PROXY_HOST}:{self.PROXY_PORT}",
                "HTTPS_PROXY": f"http://{self.PROXY_HOST}:{self.PROXY_PORT}",
                "NO_PROXY": "localhost,127.0.0.1",
            },
        )

    @classmethod
    def validate_resources(cls, sandbox_id: str, memory_mb: int, cpu_cores: float, gpu_count: int) -> None:
        if not isinstance(sandbox_id, str) or not cls.SANDBOX_ID_PATTERN.fullmatch(sandbox_id):
            raise ValueError("Sandbox ID must be 1-128 characters using letters, digits, '.', '_' or '-'")
        if not isinstance(memory_mb, int) or not 16 <= memory_mb <= 65_536:
            raise ValueError("Sandbox memory must be between 16 and 65536 MiB")
        if not isinstance(cpu_cores, (int, float)) or not 0.1 <= float(cpu_cores) <= 64:
            raise ValueError("Sandbox CPU allocation must be between 0.1 and 64 cores")
        if not isinstance(gpu_count, int) or not 0 <= gpu_count <= 16:
            raise ValueError("Sandbox GPU allocation must be between 0 and 16 devices")

    def enforce_environment(self, environment: dict[str, str], mode: str) -> dict[str, str]:
        """Prevent execution-time environment values from bypassing proxy policy."""
        safe = {k: v for k, v in environment.items()
                if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}}
        if mode == self.PROXY_NETWORK:
            safe.update(self.attachment(True).environment)
        return safe

    @staticmethod
    def validate_execution(command: Any, user: str, timeout_ms: int, max_timeout_ms: int) -> int:
        """Validate untrusted exec parameters and return the bounded timeout."""
        if user != "1000:1000":
            raise PermissionError("Sandbox execution user is fixed to the unprivileged sandbox identity")
        if not isinstance(command, list) or not command or any(not isinstance(part, str) for part in command):
            raise ValueError("Sandbox command must be a non-empty list of strings")
        if not isinstance(timeout_ms, int) or timeout_ms < 1:
            raise ValueError("Sandbox timeout must be a positive integer in milliseconds")
        if max_timeout_ms < 1:
            raise ValueError("Configured sandbox timeout ceiling must be positive")
        return min(timeout_ms, max_timeout_ms)
