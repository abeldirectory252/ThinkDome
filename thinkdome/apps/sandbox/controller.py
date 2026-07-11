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

logger = logging.getLogger(__name__)

# Lazy import for docker
docker_client: Optional[Any] = None


def get_docker_client() -> Optional[Any]:
    """Initialize and retrieve the shared Docker Engine client wrapper."""
    global docker_client
    if docker_client is not None:
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
            # Prepare resource limits
            mem_limit = f"{sandbox_model.memory_limit}m"
            nano_cpus = int(sandbox_model.cpu_limit * 1e9)

            # Spawn Docker container
            container = client.containers.run(
                image=sandbox_model.image,
                name=f"thinkdome-{sandbox_model.id}",
                detach=True,
                command="tail -f /dev/null",  # Keep container running alive
                mem_limit=mem_limit,
                nano_cpus=nano_cpus,
                network_mode="bridge" if sandbox_model.network_enabled else "none",
                labels={"thinkdome_sandbox": "true", "sandbox_id": sandbox_model.id},
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
