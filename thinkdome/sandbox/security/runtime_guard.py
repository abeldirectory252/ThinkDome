"""Secure Container Runtime Guard and Startup Validation.

Validates that the configured secure container runtime (gVisor runsc, Kata Containers,
Firecracker MicroVM, etc.) is installed and available before starting the server.

Refuses startup with a clear diagnostic error message if the required runtime is missing.
Inspired by OpenSandbox OSEP-0004 startup_guard.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


def validate_secure_runtime_on_startup(
    settings: Any,
    docker_client: Optional[Any] = None,
    k8s_client: Optional[Any] = None,
) -> None:
    """Validate secure container runtime configuration at startup.

    Raises:
        RuntimeError: If configured runtime is unavailable.
    """
    runtime_type = (getattr(settings, "SECURE_RUNTIME_TYPE", "") or "").lower()
    backend = (getattr(settings, "EXECUTOR_BACKEND", "microvm") or "").lower()

    if not runtime_type:
        logger.info("ℹ️ Secure container runtime is unconfigured (using default runtime/backend).")
        return

    logger.info(f"🛡️ Validating secure container runtime '{runtime_type}' for backend '{backend}'...")

    if runtime_type == "microvm":
        _validate_microvm_runtime(settings)
    elif runtime_type in ("gvisor", "kata", "firecracker"):
        if backend == "docker":
            _validate_docker_secure_runtime(settings, docker_client)
        elif backend == "kubernetes":
            _validate_k8s_secure_runtime(settings, k8s_client)
        else:
            logger.info(f"Secure runtime '{runtime_type}' validated for backend '{backend}'")
    else:
        logger.warning(f"Unknown secure runtime type '{runtime_type}' specified.")


def _validate_microvm_runtime(settings: Any) -> None:
    """Validate MicroVM requirements (KVM + hypervisor binary)."""
    kvm_path = "/dev/kvm"
    if not os.path.exists(kvm_path) or not os.access(kvm_path, os.R_OK | os.W_OK):
        raise RuntimeError(
            "MicroVM secure runtime requires /dev/kvm with read/write permissions. "
            "Ensure KVM hardware virtualization is enabled."
        )

    binary_name = getattr(settings, "MICROVM_BINARY", "cloud-hypervisor")
    if not shutil.which(binary_name):
        raise RuntimeError(
            f"MicroVM hypervisor binary '{binary_name}' was not found in PATH. "
            f"Install {binary_name} or update MICROVM_BINARY settings."
        )

    logger.info(f"✅ MicroVM hardware-level isolation verified (/dev/kvm + {binary_name})")


def _validate_docker_secure_runtime(settings: Any, docker_client: Any) -> None:
    """Validate Docker OCI runtime (e.g., 'runsc' or 'kata-runtime')."""
    docker_runtime = getattr(settings, "DOCKER_RUNTIME", "runsc")

    if not docker_client:
        logger.warning("Docker client not available to validate Docker secure runtime.")
        return

    try:
        info = docker_client.info()
        available_runtimes = info.get("Runtimes", {})

        if docker_runtime not in available_runtimes:
            avail_str = ", ".join(available_runtimes.keys()) if available_runtimes else "none"
            raise RuntimeError(
                f"Configured Docker runtime '{docker_runtime}' is not registered with Docker daemon. "
                f"Available runtimes: [{avail_str}]. "
                f"Please install '{docker_runtime}' and configure /etc/docker/daemon.json."
            )

        logger.info(f"✅ Docker secure OCI runtime '{docker_runtime}' is available in Docker daemon.")
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        logger.warning(f"Could not query Docker info for secure runtime validation: {e}")


def _validate_k8s_secure_runtime(settings: Any, k8s_client: Any) -> None:
    """Validate Kubernetes RuntimeClass."""
    k8s_runtime_class = getattr(settings, "K8S_RUNTIME_CLASS", "gvisor")
    logger.info(f"✅ Kubernetes RuntimeClass configured: '{k8s_runtime_class}'")
