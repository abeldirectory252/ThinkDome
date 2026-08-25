"""Application configuration via environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict

from pydantic import Field
from pydantic_settings import BaseSettings


@lru_cache()
def get_workspace_root() -> Path:
    """Dynamically resolve the project workspace root directory."""
    env_root = os.environ.get("THINKDOME_WORKSPACE") or os.environ.get("WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).resolve()

    config_dir = Path(__file__).resolve().parent
    for parent in (config_dir, *config_dir.parents):
        if (parent / "sites").exists() or (parent / "pyproject.toml").exists():
            return parent

    return Path.cwd().resolve()


# Load .env values into the environment before Pydantic reads settings.
# This makes `Settings()` support values defined in a project-root .env file.
ENV_FILE = get_workspace_root() / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class Settings(BaseSettings):
    """Global application settings loaded from env vars."""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEPLOYMENT_ENV: str = "development"  # development | test | staging | production
    NODE_ID: str = ""
    NODE_REGION: str = "default"
    NODE_AGENT_HOST: str = "127.0.0.1"
    NODE_AGENT_PORT: int = 8100
    NODE_AUTH_KEY_HEX: Optional[str] = None
    CONTROL_PLANE_INTERNAL_URL: str = ""
    REDIS_CONTROL_PLANE_CACHE_ENABLED: bool = True
    REDIS_CONTROL_PLANE_CACHE_TTL_SECONDS: int = 30
    NODE_REQUIRE_MTLS: bool = True
    NODE_TLS_CERTFILE: Optional[str] = None
    NODE_TLS_KEYFILE: Optional[str] = None
    NODE_TLS_CAFILE: Optional[str] = None

    def node_tls_config(self) -> dict[str, str]:
        """Return Uvicorn TLS settings after validating the mTLS file contract."""
        paths = {
            "ssl_certfile": self.NODE_TLS_CERTFILE,
            "ssl_keyfile": self.NODE_TLS_KEYFILE,
            "ssl_ca_certs": self.NODE_TLS_CAFILE,
        }
        if not self.NODE_REQUIRE_MTLS:
            return {}
        if not all(paths.values()):
            raise RuntimeError(
                "NODE_REQUIRE_MTLS is enabled; NODE_TLS_CERTFILE, "
                "NODE_TLS_KEYFILE, and NODE_TLS_CAFILE are required"
            )
        return {key: value for key, value in paths.items() if value}

    def validate_production_runtime(self) -> None:
        """Reject settings that cannot satisfy the production isolation contract."""
        if self.DEPLOYMENT_ENV.lower() not in {"production", "staging"}:
            return
        if self.allows_insecure_execution_fallback():
            raise RuntimeError("insecure subprocess fallback is forbidden in production/staging")
        if self.EXECUTOR_BACKEND.lower() == "subprocess":
            raise RuntimeError("subprocess execution backend is forbidden in production/staging")
        if self.EXECUTOR_BACKEND.lower() == "docker" and "@sha256:" not in self.EXECUTOR_IMAGE:
            raise RuntimeError("production Docker executor images must use an immutable @sha256 digest")
        secure_runtime = (self.SECURE_RUNTIME_TYPE or "").lower()
        if secure_runtime not in {"gvisor", "kata", "microvm", "firecracker"}:
            raise RuntimeError(
                "production/staging requires an explicitly configured hardened sandbox runtime "
                "(SECURE_RUNTIME_TYPE=gvisor, kata, microvm, or firecracker)"
            )
        if self.EXECUTOR_BACKEND.lower() == "docker" and secure_runtime not in {"gvisor", "kata"}:
            raise RuntimeError(
                "Docker production execution requires SECURE_RUNTIME_TYPE=gvisor or kata"
            )
        expected_runtime = {"gvisor": "runsc", "kata": "kata-runtime"}[secure_runtime]
        if self.DOCKER_RUNTIME != expected_runtime:
            raise RuntimeError(
                f"SECURE_RUNTIME_TYPE={secure_runtime} requires DOCKER_RUNTIME={expected_runtime}"
            )
        if self.NODE_ID and not self.CONTROL_PLANE_INTERNAL_URL:
            raise RuntimeError("production node agents require CONTROL_PLANE_INTERNAL_URL")
        if not (self.WORKSPACE_MASTER_KEY or self.VAULT_MASTER_KEY):
            raise RuntimeError("production workspaces require WORKSPACE_MASTER_KEY or VAULT_MASTER_KEY")
        if "thinkdome:thinkdome@" in self.DATABASE_URL:
            raise RuntimeError("production database must not use the default credentials")
        if "guest:guest@" in self.RABBITMQ_URL:
            raise RuntimeError("production RabbitMQ must not use the default credentials")
        jwt_secret = self.JWT_SECRET_KEY or self.SECRET_KEY
        if not jwt_secret or len(jwt_secret) < 32:
            raise RuntimeError("production JWT signing secret must be configured with at least 32 characters")
    # Comma-separated origins. Empty disables cross-origin browser requests;
    # same-origin dashboard traffic requires no CORS exception.
    CORS_ALLOW_ORIGINS: str = ""

    def cors_allow_origins(self) -> list[str]:
        """Return normalized explicit CORS origins without wildcard support."""
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

    def allows_insecure_execution_fallback(self) -> bool:
        """Whether a host-subprocess fallback is explicitly safe to use."""
        return (
            self.DEPLOYMENT_ENV.lower() in {"development", "test"}
            and self.EXECUTOR_BACKEND_USE_FALLBACK
        )

    # Executor — pluggable backends
    EXECUTOR_BACKEND: str = "docker"  # "docker" | "microvm" | "kubernetes" | "hybrid" | "subprocess"
    # This executes untrusted code on the API host and is allowed only for
    # explicitly configured local development or test environments.
    EXECUTOR_BACKEND_USE_FALLBACK: bool = False
    EXECUTOR_IMAGE: str = "thinkdome-executor:latest"

    # Docker backend settings
    DOCKER_HOST: str = "unix:///var/run/docker.sock"  # Use tcp://localhost:2376 for DinD sidecar
    DOCKER_TLS_VERIFY: bool = False                    # True when using DinD with mutual TLS
    DOCKER_CERT_PATH: Optional[str] = None             # Path to TLS certs for DinD

    # Kubernetes backend settings
    K8S_NAMESPACE: str = "thinkdome-sandboxes"
    K8S_RUNTIME_CLASS: str = "gvisor"                  # gvisor | kata | runc
    K8S_IN_CLUSTER: bool = True                        # Use in-cluster config

    # MicroVM backend settings (Cloud Hypervisor / KVM)
    MICROVM_BINARY: str = "cloud-hypervisor"           # cloud-hypervisor | firecracker
    MICROVM_KERNEL_PATH: str = "/var/lib/thinkdome/vmlinux"
    MICROVM_ROOTFS_PATH: str = "/var/lib/thinkdome/rootfs.ext4"
    MICROVM_INITRAMFS_PATH: str = "./initramfs/initramfs.cpio.gz"
    MICROVM_STATE_DIR: str = "./vm-state"
    MICROVM_BRIDGE_NAME: str = "br0"
    MICROVM_BRIDGE_IP: str = "10.20.1.1/24"
    MICROVM_BRIDGE_SUBNET: str = "10.20.1.0/24"
    MICROVM_STATEFUL_DISK_MB: int = 2048
    MICROVM_GUEST_MEM_PERCENTAGE: int = 50
    MICROVM_DEFAULT_MEM_MB: int = 512
    MICROVM_DEFAULT_VCPUS: int = 2
    MICROVM_VSOCK_PORT: int = 4032                     # Guest vsockserver port
    MICROVM_CMD_SERVER_PORT: int = 4031                # Guest HTTP command server port
    SNAPSHOT_STORAGE_DIR: str = "./storage/snapshots"

    # Execution limits
    MAX_EXEC_TIMEOUT_MS: int = 10000
    CPU_TIME_LIMIT_SEC: int = 5
    MEMORY_LIMIT_MB: int = 128
    MAX_OUTPUT_BYTES: int = 1_048_576  # 1 MB
    MCP_MAX_MESSAGE_BYTES: int = Field(default=1_048_576, ge=16_384, le=16_777_216)
    REQUEST_LOG_MAX_PAYLOAD_BYTES: int = Field(default=262_144, ge=16_384, le=16_777_216)
    EXECUTION_HOOK_TIMEOUT_MS: int = Field(default=5000, ge=100, le=120_000)

    # GPU support
    GPU_ENABLED: bool = False
    GPU_MAX_PER_SANDBOX: int = 1
    GPU_DEVICE_TYPE: str = "nvidia.com/gpu"  # K8s resource name

    # File management
    MAX_FILE_SIZE_MB: int = 10
    FILE_STORAGE_DIR: str = "./storage"
    FILEBOX_DEFAULT_QUOTA_MB: int = 10240

    # Security
    API_KEY: Optional[str] = None  # Optional: set to enable API key auth
    JWT_SECRET_KEY: Optional[str] = None
    SECRET_KEY: Optional[str] = None

    # ── Production Infrastructure ──
    DATABASE_URL: str = "postgresql://thinkdome:thinkdome@localhost:5432/thinkdome"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── OpenTelemetry ──
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "thinkdome-api"

    # ── Idle Detection ──
    IDLE_TIMEOUT_SEC: int = 600  # Auto-terminate sandboxes idle > 10 min

    # Search Tool Settings
    SEARCH_PROVIDER: str = "duckduckgo"
    TAVILY_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None
    SEARCH_RATE_LIMIT: int = 30
    SEARCH_MAX_RESULTS: int = 10

    # SMTP Email Settings
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None        # Default sender address
    SMTP_USE_TLS: bool = True

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # ── Pool Manager Settings ──
    POOL_MIN_WARM: int = 3              # Minimum pre-warmed containers
    POOL_MAX_SIZE: int = 50             # Maximum pool capacity
    POOL_EVICTION_GRACE_SEC: int = 30   # Lazy eviction grace period (seconds)
    POOL_DEMAND_WINDOW_SEC: int = 60    # Demand estimation rolling window (seconds)
    POOL_ENABLED: bool = True           # Enable/disable pool manager

    # ── Monitor Settings ──
    MONITOR_POLL_INTERVAL_SEC: float = 2.0    # Metrics collection interval
    MONITOR_RETENTION_SEC: int = 300          # Metrics history retention (5 min)
    MONITOR_ALERT_COOLDOWN_SEC: int = 60      # Alert dedup cooldown

    # ── Credential Vault Settings ──
    VAULT_MASTER_KEY: Optional[str] = None    # Fernet key for vault encryption
    WORKSPACE_MASTER_KEY: Optional[str] = None  # Master key for workspace encryption at rest

    # ── Secure Container Runtime Settings ──
    SECURE_RUNTIME_TYPE: str = ""             # "", "gvisor", "kata", "firecracker", "microvm"
    DOCKER_RUNTIME: str = "runsc"              # OCI runtime name for Docker mode ("runsc", "kata-runtime")
    K8S_RUNTIME_CLASS: str = "gvisor"         # K8s RuntimeClass ("gvisor", "kata-qemu", "kata-fc")

    # ── Secure Access & Signed Route Settings (OSEP-0011) ──
    SECURE_ACCESS_KEYS: Dict[str, str] = {}   # Map of key_id -> secret_hex (e.g. {"a": "secret123"})
    SECURE_ACCESS_ACTIVE_KEY_ID: str = "a"

    model_config = {"env_prefix": "", "case_sensitive": True}


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    # Site data is tenant-scoped. Unless explicitly overridden, keep each
    # site's storage under its own site directory rather than repository root.
    site_name = os.environ.get("THINKDOME_SITE", "think.local")
    site_config = get_workspace_root() / "sites" / site_name / "site_config.json"
    if site_config.exists() and settings.FILE_STORAGE_DIR == "./storage":
        settings.FILE_STORAGE_DIR = str(site_config.parent / "storage")
        settings.SNAPSHOT_STORAGE_DIR = str(site_config.parent / "storage" / "snapshots")
    return settings
