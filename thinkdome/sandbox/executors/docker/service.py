"""Dedicated Docker Executor Control-Plane Service (DIND-002).

This service is the ONLY component in the architecture that directly communicates
with the Docker-in-Docker (DinD) daemon. It exposes a hardened, authenticated REST API
for sandbox container lifecycle management, code execution, file transfers, and monitoring.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tarfile
import time
from typing import Any, Dict, List, Optional

import docker
import docker.errors
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from thinkdome.core.config import Settings, get_settings
from thinkdome.sandbox.executors.docker.container_policy import (
    DockerContainerPolicy,
    DockerExecutionPolicy,
)
from thinkdome.sandbox.network.docker_policy import DockerSandboxPolicy
from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup

logger = logging.getLogger(__name__)


import hmac
import re

ID_REGEX = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"

# ── Request / Response Schemas ──────────────────────────────────────────────────

class CreateSandboxRequest(BaseModel):
    sandbox_id: str = Field(..., pattern=ID_REGEX, description="Unique sandbox identifier")
    tenant_id: str = Field(default="default", pattern=ID_REGEX, description="Tenant or workspace ID")
    owner: str = Field(default="anonymous", pattern=ID_REGEX, description="Authenticated user ID")
    memory_mb: int = Field(default=128, ge=16, le=65536)
    cpu_cores: float = Field(default=1.0, ge=0.1, le=64.0)
    network_enabled: bool = Field(default=False)
    gpu_count: int = Field(default=0, ge=0, le=8)
    role: str = Field(default="AGENT_STANDARD")


class ExecRequest(BaseModel):
    command: List[str] = Field(..., description="Command and arguments list")
    user: str = Field(default="1000:1000", description="User ID inside container")
    env_vars: Optional[Dict[str, str]] = Field(default=None)
    timeout_ms: int = Field(default=10000, ge=100, le=600000)
    tenant_id: str = Field(default="default", pattern=ID_REGEX)
    owner: str = Field(default="anonymous", pattern=ID_REGEX)


class SandboxActionRequest(BaseModel):
    tenant_id: str = Field(default="default", pattern=ID_REGEX)
    owner: str = Field(default="anonymous", pattern=ID_REGEX)


class CopyInRequest(BaseModel):
    archive_b64: str = Field(..., description="Base64-encoded tar archive")
    destination_path: str = Field(default="/workspace")
    tenant_id: str = Field(default="default")
    owner: str = Field(default="anonymous")


class PoolAcquireRequest(BaseModel):
    role: str = Field(default="LLM")
    tenant_id: str = Field(default="default")
    owner: str = Field(default="anonymous")


class PoolReleaseRequest(BaseModel):
    pool_id: str
    tenant_id: str = Field(default="default")
    owner: str = Field(default="anonymous")


# ── Service Definition ──────────────────────────────────────────────────────────

class DockerExecutorServiceApp:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.client: Optional[docker.DockerClient] = None
        self.network_policy: Optional[DockerSandboxPolicy] = None
        self._seccomp_profile: Optional[dict] = None
        self.app = FastAPI(
            title="ThinkDome Docker Executor Service",
            description="Isolated Docker-in-Docker Control Plane Service",
            version="1.0.0",
        )
        self._setup_routes()

    def initialize_docker_client(self) -> None:
        """Connect to DinD daemon using TLS certificates if configured."""
        try:
            if self.settings.DOCKER_TLS_VERIFY and self.settings.DOCKER_CERT_PATH:
                from docker.tls import TLSConfig
                tls_config = TLSConfig(
                    client_cert=(
                        os.path.join(self.settings.DOCKER_CERT_PATH, "cert.pem"),
                        os.path.join(self.settings.DOCKER_CERT_PATH, "key.pem"),
                    ),
                    ca_cert=os.path.join(self.settings.DOCKER_CERT_PATH, "ca.pem"),
                    verify=True,
                )
                self.client = docker.DockerClient(
                    base_url=self.settings.DOCKER_HOST,
                    tls=tls_config,
                )
            else:
                self.client = docker.DockerClient(base_url=self.settings.DOCKER_HOST)
            self.client.ping()
            self.network_policy = DockerSandboxPolicy(self.client)
            logger.info(f"✅ DockerExecutorService connected to Docker daemon at {self.settings.DOCKER_HOST}")
        except Exception as e:
            logger.error(f"❌ DockerExecutorService failed to connect to Docker daemon: {e}")
            self.client = None

        # Load seccomp profile
        from thinkdome.core.config import get_workspace_root
        seccomp_path = get_workspace_root() / "security" / "seccomp.json"
        if seccomp_path.exists():
            try:
                self._seccomp_profile = json.loads(seccomp_path.read_text())
            except Exception as e:
                logger.error(f"Failed to load seccomp.json: {e}")

    def _verify_auth(self, x_executor_auth: Optional[str] = Header(None)) -> None:
        """Enforce strict service-to-service authentication."""
        auth_token = self.settings.EXECUTOR_CONTROL_AUTH_TOKEN
        if not auth_token:
            if self.settings.DEPLOYMENT_ENV.lower() in {"production", "staging"}:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="EXECUTOR_CONTROL_AUTH_TOKEN must be configured in production",
                )
            return  # Allowed in local development mode without token

        if not x_executor_auth or x_executor_auth != auth_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing executor control-plane authentication token",
            )

    def _get_container_by_sandbox_id(self, sandbox_id: str) -> docker.models.containers.Container:
        """Find container by sandbox_id label or name."""
        if not re.fullmatch(ID_REGEX, sandbox_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sandbox not found",
            )
        if not self.client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Docker daemon connection unavailable",
            )
        try:
            return self.client.containers.get(f"thinkdome-sb-{sandbox_id}")
        except docker.errors.NotFound:
            # Fallback: search by label
            containers = self.client.containers.list(
                all=True,
                filters={"label": f"thinkdome.sandbox_id={sandbox_id}"},
            )
            if containers:
                return containers[0]
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sandbox '{sandbox_id}' not found",
            )

    def _validate_ownership(
        self,
        container: docker.models.containers.Container,
        sandbox_id: str,
        tenant_id: str,
        owner: str,
    ) -> None:
        """Enforce strict server-side authorization and boundary checks."""
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        container_sandbox_id = labels.get("thinkdome.sandbox_id")
        container_tenant_id = labels.get("thinkdome.tenant_id", "default")
        container_owner = labels.get("thinkdome.owner", "anonymous")

        if container_sandbox_id != sandbox_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sandbox container identity mismatch",
            )

        if tenant_id != "system" and container_tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-tenant operation denied for sandbox '{sandbox_id}'",
            )

        if owner != "system" and container_owner != owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-owner operation denied for sandbox '{sandbox_id}'",
            )

    def _setup_routes(self) -> None:
        app = self.app

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            
            auth_token = self.settings.EXECUTOR_CONTROL_AUTH_TOKEN
            if auth_token:
                x_auth = request.headers.get("X-Executor-Auth", "")
                if not hmac.compare_digest(x_auth, auth_token):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid or missing executor control-plane authentication token"},
                    )
            elif self.settings.DEPLOYMENT_ENV.lower() in {"production", "staging"}:
                return JSONResponse(
                    status_code=500,
                    content={"detail": "EXECUTOR_CONTROL_AUTH_TOKEN must be configured in production"},
                )

            return await call_next(request)

        @app.get("/health")
        async def health():
            if not self.client:
                return JSONResponse(
                    status_code=503,
                    content={"status": "unhealthy", "error": "Docker daemon connection unavailable"},
                )
            try:
                self.client.ping()
                return {"status": "healthy", "executor_backend": "docker", "mode": "isolated_control_plane"}
            except Exception as e:
                return JSONResponse(
                    status_code=503,
                    content={"status": "unhealthy", "error": str(e)},
                )

        @app.post("/v1/sandboxes/create")
        async def create_sandbox(req: CreateSandboxRequest):
            if not self.client:
                raise HTTPException(status_code=503, detail="Docker daemon unavailable")

            DockerSandboxPolicy.validate_resources(req.sandbox_id, req.memory_mb, req.cpu_cores, req.gpu_count)

            runtime = DockerContainerPolicy.runtime(self.settings)

            security_opt = ["no-new-privileges:true"]
            if self._seccomp_profile:
                security_opt.append(f"seccomp={json.dumps(self._seccomp_profile)}")

            device_requests = []
            if req.gpu_count > 0:
                device_requests.append(
                    docker.types.DeviceRequest(count=req.gpu_count, capabilities=[["gpu"]])
                )

            attachment = self.network_policy.attachment(req.network_enabled)

            def _do_create():
                return self.client.containers.run(
                    image=self.settings.EXECUTOR_IMAGE,
                    command=["sleep", "infinity"],
                    detach=True,
                    name=f"thinkdome-sb-{req.sandbox_id}",
                    labels={
                        "thinkdome.sandbox_id": req.sandbox_id,
                        "thinkdome.tenant_id": req.tenant_id,
                        "thinkdome.owner": req.owner,
                        "thinkdome.security_profile": "restricted",
                    },
                    mem_limit=f"{req.memory_mb}m",
                    memswap_limit=f"{req.memory_mb}m",
                    nano_cpus=int(req.cpu_cores * 1e9),
                    user="1000:1000",
                    read_only=True,
                    tmpfs={
                        "/tmp": f"size={DockerContainerPolicy._bounded_size(self.settings, 'SANDBOX_TMPFS_SIZE_MB', 64, 4096)}m,noexec,nosuid,nodev,mode=1777",
                        "/workspace": f"size={DockerContainerPolicy._bounded_size(self.settings, 'SANDBOX_TMPFS_SIZE_MB', 64, 4096)}m,noexec,nosuid,nodev,mode=1777",
                    },
                    cap_drop=["ALL"],
                    privileged=False,
                    security_opt=security_opt,
                    pids_limit=100,
                    ipc_mode="private",
                    shm_size=DockerContainerPolicy.shm_size(self.settings),
                    ulimits=DockerContainerPolicy.nofile_ulimit(self.settings),
                    network_mode=attachment.mode,
                    environment=attachment.environment,
                    runtime=runtime,
                    device_requests=device_requests,
                    init=True,
                )

            loop = asyncio.get_event_loop()
            try:
                container = await loop.run_in_executor(None, _do_create)
                return {
                    "sandbox_id": req.sandbox_id,
                    "container_id": container.id,
                    "status": "created",
                    "network_mode": attachment.mode,
                }
            except Exception as e:
                logger.error(f"Failed to create container for sandbox '{req.sandbox_id}': {e}")
                raise HTTPException(status_code=500, detail=f"Container creation failed: {e}")

        @app.post("/v1/sandboxes/{sandbox_id}/start")
        async def start_sandbox(sandbox_id: str, req: SandboxActionRequest = SandboxActionRequest()):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, container.start)
            return {"sandbox_id": sandbox_id, "status": "running"}

        @app.post("/v1/sandboxes/{sandbox_id}/exec")
        async def exec_sandbox(sandbox_id: str, req: ExecRequest):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

            effective_timeout_ms = DockerSandboxPolicy.validate_execution(
                req.command, req.user, req.timeout_ms, int(self.settings.MAX_EXEC_TIMEOUT_MS)
            )

            actual_mode = str((container.attrs.get("HostConfig") or {}).get("NetworkMode", "none"))
            execution_env = DockerExecutionPolicy.sanitize_environment(dict(req.env_vars or {}))
            execution_env = self.network_policy.enforce_environment(execution_env, actual_mode)
            execution_env["PATH"] = DockerExecutionPolicy.SAFE_PATH

            loop = asyncio.get_event_loop()
            start = time.perf_counter()

            def _do_exec():
                res = container.exec_run(
                    cmd=req.command,
                    user=req.user,
                    environment=execution_env,
                    workdir="/workspace",
                )
                return res.exit_code, res.output

            try:
                exit_code, output = await asyncio.wait_for(
                    loop.run_in_executor(None, _do_exec),
                    timeout=effective_timeout_ms / 1000.0,
                )
                duration_ms = (time.perf_counter() - start) * 1000.0
                return {
                    "sandbox_id": sandbox_id,
                    "stdout": output.decode("utf-8", errors="ignore") if isinstance(output, bytes) else str(output),
                    "stderr": "",
                    "exit_code": exit_code,
                    "timed_out": False,
                    "duration_ms": duration_ms,
                }
            except asyncio.TimeoutError:
                try:
                    await loop.run_in_executor(None, lambda: (container.kill(), container.remove(force=True)))
                except Exception as kill_err:
                    logger.warning(f"Failed to kill timed-out container {container.id}: {kill_err}")

                duration_ms = (time.perf_counter() - start) * 1000.0
                return {
                    "sandbox_id": sandbox_id,
                    "stdout": "",
                    "stderr": "Execution timed out.",
                    "exit_code": -1,
                    "timed_out": True,
                    "duration_ms": duration_ms,
                }

        @app.post("/v1/sandboxes/{sandbox_id}/stop")
        async def stop_sandbox(sandbox_id: str, req: SandboxActionRequest = SandboxActionRequest()):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: container.stop(timeout=2))
            return {"sandbox_id": sandbox_id, "status": "stopped"}

        @app.post("/v1/sandboxes/{sandbox_id}/restart")
        async def restart_sandbox(sandbox_id: str, req: SandboxActionRequest = SandboxActionRequest()):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: container.restart(timeout=2))
            return {"sandbox_id": sandbox_id, "status": "restarted"}

        @app.post("/v1/sandboxes/{sandbox_id}/destroy")
        async def destroy_sandbox(sandbox_id: str, req: SandboxActionRequest = SandboxActionRequest()):
            try:
                container = self._get_container_by_sandbox_id(sandbox_id)
                self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: container.remove(force=True))
            except HTTPException as he:
                if he.status_code == 404:
                    return {"sandbox_id": sandbox_id, "status": "destroyed"}
                raise
            except Exception as e:
                logger.debug(f"Container removal warning for '{sandbox_id}': {e}")

            return {"sandbox_id": sandbox_id, "status": "destroyed"}

        @app.get("/v1/sandboxes/{sandbox_id}/inspect")
        async def inspect_sandbox(sandbox_id: str, tenant_id: str = "default", owner: str = "anonymous"):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, tenant_id, owner)

            return {
                "sandbox_id": sandbox_id,
                "container_id": container.id,
                "status": container.status,
                "labels": container.labels,
                "network_mode": (container.attrs.get("HostConfig") or {}).get("NetworkMode", "none"),
                "created": container.attrs.get("Created"),
                "state": container.attrs.get("State", {}),
            }

        @app.get("/v1/sandboxes/{sandbox_id}/logs")
        async def get_sandbox_logs(
            sandbox_id: str,
            tail: int = 100,
            timestamps: bool = False,
            tenant_id: str = "default",
            owner: str = "anonymous",
        ):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, tenant_id, owner)

            loop = asyncio.get_event_loop()
            bounded_tail = min(max(1, tail), 1000)
            raw_logs = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=True, stderr=True, tail=bounded_tail, timestamps=timestamps),
            )
            return {"sandbox_id": sandbox_id, "logs": raw_logs.decode("utf-8", errors="ignore")}

        @app.post("/v1/sandboxes/{sandbox_id}/files/copy_in")
        async def copy_in(sandbox_id: str, req: CopyInRequest):
            import base64
            archive_bytes = base64.b64decode(req.archive_b64)
            if len(archive_bytes) > self.settings.EXECUTOR_CONTROL_MAX_PAYLOAD_BYTES:
                raise HTTPException(status_code=400, detail="Archive exceeds maximum payload size limit")

            fileobj = io.BytesIO(archive_bytes)
            with tarfile.open(fileobj=fileobj, mode="r:*") as tar:
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name.split("/"):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Security violation: path traversal prohibited in archive member '{member.name}'",
                        )

            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, req.tenant_id, req.owner)

            fileobj.seek(0)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: container.put_archive(req.destination_path, fileobj),
            )
            return {"sandbox_id": sandbox_id, "status": "copied"}

        @app.post("/v1/sandboxes/cleanup")
        async def cleanup_timed_out():
            if not self.client:
                return {"cleaned": 0}

            loop = asyncio.get_event_loop()

            def _do_cleanup():
                containers = self.client.containers.list(
                    all=True,
                    filters={"label": "thinkdome.sandbox_id"},
                )
                cleaned = 0
                for c in containers:
                    state = c.attrs.get("State", {})
                    if state.get("Status") == "exited":
                        try:
                            c.remove(force=True)
                            cleaned += 1
                        except Exception:
                            pass
                return cleaned

            count = await loop.run_in_executor(None, _do_cleanup)
            return {"cleaned": count}

        @app.get("/v1/sandboxes/{sandbox_id}/metrics")
        async def get_sandbox_metrics(sandbox_id: str, tenant_id: str = "default", owner: str = "anonymous"):
            container = self._get_container_by_sandbox_id(sandbox_id)
            self._validate_ownership(container, sandbox_id, tenant_id, owner)

            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(
                None,
                lambda: container.stats(stream=False),
            )
            return {"sandbox_id": sandbox_id, "stats": stats}


# Singleton app getter for standalone server runner
_service_instance: Optional[DockerExecutorServiceApp] = None

def get_executor_app(settings: Optional[Settings] = None) -> FastAPI:
    global _service_instance
    if _service_instance is None:
        _service_instance = DockerExecutorServiceApp(settings)
        _service_instance.initialize_docker_client()
    return _service_instance.app
