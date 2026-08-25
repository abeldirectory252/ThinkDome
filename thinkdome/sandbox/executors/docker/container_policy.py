"""Shared Docker container security policy for all executor lifecycles."""

from __future__ import annotations

from typing import Any

from thinkdome.sandbox.executors.host.bubblewrap import (
    _BLOCKED_INTERPRETER_ENV_KEYS,
    _is_env_var_sensitive,
)


class DockerContainerPolicy:
    """Build and validate immutable security invariants for Docker containers."""

    RUNTIME_BY_PROFILE = {"gvisor": "runsc", "kata": "kata-runtime"}
    DEFAULT_POOL_MEMORY = "256m"
    DEFAULT_POOL_CPU_NANOS = 500_000_000
    DEFAULT_POOL_PIDS = 20

    @staticmethod
    def _bounded_size(settings: Any, name: str, default: int, maximum: int) -> int:
        value = getattr(settings, name, default)
        if type(value) is not int or not 16 <= value <= maximum:
            raise ValueError(f"{name} must be between 16 and {maximum} MiB")
        return value

    @classmethod
    def shm_size(cls, settings: Any) -> str:
        return f"{cls._bounded_size(settings, 'SHM_SIZE_MB', 64, 1024)}m"

    @classmethod
    def nofile_ulimit(cls, settings: Any) -> list[dict[str, int | str]]:
        limit = cls._bounded_size(settings, "SANDBOX_NOFILE_LIMIT", 1024, 65_536)
        return [{"name": "nofile", "soft": limit, "hard": limit}]

    @staticmethod
    def runtime(settings: Any) -> str | None:
        secure_type = str(getattr(settings, "SECURE_RUNTIME_TYPE", "")).lower()
        if not secure_type:
            return None
        expected = DockerContainerPolicy.RUNTIME_BY_PROFILE.get(secure_type)
        configured = getattr(settings, "DOCKER_RUNTIME", "runsc")
        if expected is None or configured != expected:
            raise RuntimeError(f"Secure runtime configuration mismatch: {secure_type}")
        return configured

    @classmethod
    def pool_config(
        cls,
        settings: Any,
        image: str,
        security_opt: list[str],
        device_requests: list[Any],
    ) -> dict[str, Any]:
        config = {
            "image": image,
            "entrypoint": "",
            "command": ["sleep", "infinity"],
            "detach": True,
            "user": "1000:1000",
            "read_only": True,
            "tmpfs": cls._tmpfs_config(settings),
            "cap_drop": ["ALL"],
            "privileged": False,
            "security_opt": security_opt,
            "network_mode": "none",
            "ipc_mode": "private",
            "shm_size": cls.shm_size(settings),
            "ulimits": cls.nofile_ulimit(settings),
            "nano_cpus": cls.DEFAULT_POOL_CPU_NANOS,
            "mem_limit": cls.DEFAULT_POOL_MEMORY,
            "memswap_limit": cls.DEFAULT_POOL_MEMORY,
            "pids_limit": cls.DEFAULT_POOL_PIDS,
            "init": True,
            "device_requests": device_requests or None,
        }
        runtime = cls.runtime(settings)
        if runtime:
            config["runtime"] = runtime
        return config

    @staticmethod
    def _tmpfs_config(settings: Any) -> dict[str, str]:
        size = DockerContainerPolicy._bounded_size(settings, "SANDBOX_TMPFS_SIZE_MB", 64, 4096)
        return {
            "/tmp": f"size={size}m,noexec,nosuid,nodev",
            "/workspace": f"size={size}m,noexec,nosuid,nodev",
        }


class DockerExecutionPolicy:
    """Reusable request-boundary policy shared by every Docker executor path."""

    NETWORK_AUTHORIZED_ROLES = frozenset({"ADMIN", "ORCH", "IDE", "WEB", "SDK", "CURL"})
    RESOURCE_CUSTOMIZATION_ROLES = frozenset({"ADMIN", "ORCH", "IDE"})
    PROXY_VARIABLES = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"})
    SAFE_PATH = "/sbin:/usr/sbin:/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"

    @classmethod
    def sanitize_environment(cls, values: dict[str, str] | None) -> dict[str, str]:
        """Remove interpreter, proxy, and sensitive host environment inputs."""
        if values is not None and not isinstance(values, dict):
            raise ValueError("Environment must be a mapping of string keys and values")
        safe: dict[str, str] = {}
        total_bytes = 0
        for key, value in (values or {}).items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Environment keys and values must be strings")
            if len(key) > 256 or len(value.encode("utf-8")) > 16_384:
                raise ValueError("Environment variable exceeds the allowed size")
            upper = key.upper()
            if upper in _BLOCKED_INTERPRETER_ENV_KEYS or upper in cls.PROXY_VARIABLES:
                continue
            if _is_env_var_sensitive(key):
                continue
            total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
            if total_bytes > 65_536:
                raise ValueError("Environment exceeds the 65536-byte execution limit")
            safe[key] = value
        return safe
