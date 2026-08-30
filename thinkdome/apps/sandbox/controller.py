"""Sandbox Container Controller.

Interfaces with the Docker Engine to create, start, stop, execute commands in,
and destroy container sandboxes.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, Generator, List, Optional

from thinkdome.apps.sandbox.models import Sandbox
from thinkdome.core.hooks.hooks import manager as hook_manager
from thinkdome.core.events.events import emit
from thinkdome.core.config import get_settings
from thinkdome.sandbox.executors.docker.container_policy import DockerContainerPolicy
from thinkdome.sandbox.network.docker_policy import DockerSandboxPolicy

logger = logging.getLogger(__name__)

# Lazy import for docker
docker_client: Optional[Any] = None


def get_docker_client() -> Optional[Any]:
    """Initialize and retrieve the shared Docker Engine client wrapper or remote executor client."""
    global docker_client
    if docker_client is not None:
        return docker_client
    settings = get_settings()
    if settings.EXECUTOR_CONTROL_URL or settings.DEPLOYMENT_ENV.lower() in ("production", "staging"):
        from thinkdome.sandbox.executors.docker.client import DockerExecutorClient, DockerClientShim
        executor_client = DockerExecutorClient(settings)
        docker_client = DockerClientShim(executor_client)
        return docker_client
    try:
        import docker
        docker_client = docker.from_env()
        return docker_client
    except Exception as e:
        logger.warning(f"Docker engine client unavailable: {e}. Subprocess/Mock fallback will be used.")
        return None


async def create_sandbox(sandbox_model: Sandbox) -> str:
    """Provision and start a container matching the model limits."""
    # Run before_provision hook
    await hook_manager.run("sandbox.before_provision", sandbox_model)
    sandbox_model.status = "Provisioning"
    sandbox_model.save()

    client = get_docker_client()
    if client:
        try:
            settings = get_settings()
            DockerSandboxPolicy.validate_resources(
                str(sandbox_model.id),
                int(sandbox_model.memory_limit),
                float(sandbox_model.cpu_limit),
                0,
            )
            # Never allow the model/client to select an arbitrary image. The
            # configured executor image is the reviewed, immutable boundary.
            attachment = DockerSandboxPolicy(client).attachment(bool(sandbox_model.network_enabled))
            tmpfs = DockerContainerPolicy._tmpfs_config(settings)
            security_opt = ["no-new-privileges:true"]
            runtime = DockerContainerPolicy.runtime(settings)
            if runtime:
                runtime_kwargs = {"runtime": runtime}
            else:
                runtime_kwargs = {}

            # Spawn Docker container
            container = client.containers.run(
                image=settings.EXECUTOR_IMAGE,
                name=f"thinkdome-{sandbox_model.id}",
                detach=True,
                command=["sleep", "infinity"],
                user="1000:1000",
                read_only=True,
                tmpfs=tmpfs,
                cap_drop=["ALL"],
                privileged=False,
                security_opt=security_opt,
                pids_limit=100,
                ipc_mode="private",
                shm_size=DockerContainerPolicy.shm_size(settings),
                ulimits=DockerContainerPolicy.nofile_ulimit(settings),
                mem_limit=f"{int(sandbox_model.memory_limit)}m",
                memswap_limit=f"{int(sandbox_model.memory_limit)}m",
                nano_cpus=int(float(sandbox_model.cpu_limit) * 1e9),
                network_mode=attachment.mode,
                environment=attachment.environment,
                labels={
                    "thinkdome_sandbox": "true",
                    "thinkdome.sandbox_id": str(sandbox_model.id),
                    "thinkdome.security_profile": "restricted",
                },
                init=True,
                **runtime_kwargs,
            )
            logger.info(f"✓ Provisioned Docker container {container.short_id} for sandbox {sandbox_model.id}")
        except Exception as e:
            logger.error(f"Failed to provision Docker container: {e}")
            sandbox_model.status = "Stopped"
            sandbox_model.save()
            raise e
    else:
        # Fallback dry-run mock mode
        logger.info(f"[Dry-run] Provisioned mock sandbox {sandbox_model.id}")

    await hook_manager.run("sandbox.after_provision", sandbox_model)

    # Start Sandbox runtime
    await start_sandbox(sandbox_model)
    return sandbox_model.id


async def start_sandbox(sandbox_model: Sandbox) -> None:
    """Activate container execution context and update model status."""
    await hook_manager.run("sandbox.before_start", sandbox_model)

    client = get_docker_client()
    if client:
        try:
            container = client.containers.get(f"thinkdome-{sandbox_model.id}")
            container.start()
        except Exception as e:
            logger.error(f"Failed to start container: {e}")

    sandbox_model.status = "Running"
    sandbox_model.save()

    # Emit global event
    await emit("sandbox.started", {"sandbox_id": sandbox_model.id, "owner": sandbox_model.owner})
    await hook_manager.run("sandbox.after_start", sandbox_model)


async def stop_sandbox(sandbox_model: Sandbox) -> None:
    """Stop active container execution context."""
    await hook_manager.run("sandbox.before_stop", sandbox_model)

    client = get_docker_client()
    if client:
        try:
            container = client.containers.get(f"thinkdome-{sandbox_model.id}")
            container.stop(timeout=5)
        except Exception as e:
            logger.warning(f"Error stopping container context: {e}")

    sandbox_model.status = "Stopped"
    sandbox_model.save()

    # Emit global event
    await emit("sandbox.stopped", {"sandbox_id": sandbox_model.id})
    await hook_manager.run("sandbox.after_stop", sandbox_model)


async def destroy_sandbox(sandbox_model: Sandbox) -> None:
    """Remove container runtime from host system and mark sandbox deleted."""
    await hook_manager.run("sandbox.before_destroy", sandbox_model)

    client = get_docker_client()
    if client:
        try:
            container = client.containers.get(f"thinkdome-{sandbox_model.id}")
            container.remove(force=True)
            logger.info(f"✓ Removed container context for sandbox {sandbox_model.id}")
        except Exception as e:
            logger.warning(f"Could not remove container structure: {e}")

    sandbox_model.status = "Destroyed"
    sandbox_model.save()
    sandbox_model.delete(soft=True)

    await emit("sandbox.destroyed", {"sandbox_id": sandbox_model.id})
    await hook_manager.run("sandbox.after_destroy", sandbox_model)


def execute_command(sandbox_model: Sandbox, cmd: str) -> Dict[str, Any]:
    """Execute shell command inside sandbox context and return result dict."""
    client = get_docker_client()
    if client:
        try:
            container = client.containers.get(f"thinkdome-{sandbox_model.id}")
            exit_code, output = container.exec_run(cmd)
            return {"exit_code": exit_code, "output": output.decode("utf-8")}
        except Exception as e:
            return {"exit_code": 1, "error": str(e)}
    else:
        # Mock shell execution
        logger.info(f"[Dry-run] Executing command: {cmd}")
        return {"exit_code": 0, "output": f"Mock output for: {cmd}"}
