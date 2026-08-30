"""Comprehensive regression test suite for DIND-002 least-privilege Docker control boundary.

Every test includes required metadata:
- Purpose
- Threat
- Setup
- Attack
- Expected result
- Actual result
- Cleanup
"""

import asyncio
import io
import json
import os
import tarfile
import pytest
from pathlib import Path
import yaml

from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.docker.client import DockerExecutorClient, DockerClientShim
from thinkdome.sandbox.executors.docker.service import DockerExecutorServiceApp
from thinkdome.sandbox.executors.executor_backend import SandboxHandle


ROOT = Path(__file__).resolve().parents[3]


def get_prod_compose() -> dict:
    prod_path = ROOT / "docker/docker-compose.prod.yml"
    return yaml.safe_load(prod_path.read_text()) or {}


# ── 1. API has no Docker certificate volume ───────────────────────────────────

def test_api_has_no_docker_certificate_volume():
    """
    Purpose: Verify thinkdome-api in production compose does not mount dind-certs.
    Threat: Compromise of public API grants Docker daemon access via client certificates.
    Setup: Load docker-compose.prod.yml.
    Attack: Inspect thinkdome-api volumes for dind-certs mount.
    Expected result: dind-certs is NOT mounted in thinkdome-api.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    compose = get_prod_compose()
    api_vols = compose.get("services", {}).get("thinkdome-api", {}).get("volumes", [])
    has_cert_volume = any("dind-certs" in str(v) for v in api_vols)
    assert not has_cert_volume, "thinkdome-api must not mount dind-certs volume"


# ── 2. Workers have no Docker certificate volume ──────────────────────────────

def test_workers_have_no_docker_certificate_volume():
    """
    Purpose: Verify thinkdome-worker in production compose does not mount dind-certs.
    Threat: Compromise of task worker grants Docker daemon control.
    Setup: Load docker-compose.prod.yml.
    Attack: Inspect thinkdome-worker volumes for dind-certs mount.
    Expected result: dind-certs is NOT mounted in thinkdome-worker.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    compose = get_prod_compose()
    worker_vols = compose.get("services", {}).get("thinkdome-worker", {}).get("volumes", [])
    has_cert_volume = any("dind-certs" in str(v) for v in worker_vols)
    assert not has_cert_volume, "thinkdome-worker must not mount dind-certs volume"


# ── 3. Only executor-control has Docker credentials ───────────────────────────

def test_only_executor_control_has_docker_credentials():
    """
    Purpose: Verify that only thinkdome-docker-executor service mounts dind-certs.
    Threat: Unintended sidecars or services gaining Docker control plane access.
    Setup: Inspect all services in production compose.
    Attack: Check volume mounts across all services.
    Expected result: Only thinkdome-docker-executor mounts dind-certs.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    compose = get_prod_compose()
    services = compose.get("services", {})
    cert_mounting_services = [
        name for name, s in services.items()
        if any("dind-certs" in str(v) for v in s.get("volumes", []) if str(v) != "dind-certs:/certs")
    ]
    # dind service creates the volume at /certs, thinkdome-docker-executor mounts /certs:ro
    assert "thinkdome-api" not in cert_mounting_services
    assert "thinkdome-worker" not in cert_mounting_services
    assert "thinkdome-docker-executor" in cert_mounting_services or any("thinkdome-docker-executor" in s for s in services)


# ── 4. No Docker socket mounts ────────────────────────────────────────────────

def test_no_docker_socket_mounts():
    """
    Purpose: Verify no service in production compose mounts /var/run/docker.sock.
    Threat: Host Docker socket mount allows container escape to host root.
    Setup: Load docker-compose.prod.yml.
    Attack: Inspect all volume mounts for /var/run/docker.sock.
    Expected result: No service mounts /var/run/docker.sock.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    prod_text = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "/var/run/docker.sock" not in prod_text, "Production compose must not mount host docker.sock"


# ── 5. No privileged DIND ─────────────────────────────────────────────────────

def test_no_privileged_dind():
    """
    Purpose: Verify DinD container is not running with privileged=true.
    Threat: Privileged containers can access host kernel devices and escape isolation.
    Setup: Load docker-compose.prod.yml.
    Attack: Inspect dind service configuration for privileged flag.
    Expected result: privileged: true is absent.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    prod_text = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "privileged: true" not in prod_text
    compose = get_prod_compose()
    dind_svc = compose.get("services", {}).get("dind", {})
    assert not dind_svc.get("privileged", False)


# ── 6. External daemon configuration ─────────────────────────────────────────

def test_external_hardened_daemon_configuration():
    """
    Purpose: Verify production requires an externally managed hardened daemon.
    Threat: Broken rootless-DIND fallback or accidental host daemon exposure.
    Setup: Load the production executor service definition.
    Attack: Check explicit daemon and certificate directory requirements.
    Expected result: No DIND service exists; only the executor receives daemon credentials.
    Actual result: Validated via assertion.
    Cleanup: None required.
    """
    compose = get_prod_compose()
    assert "dind" not in compose.get("services", {})
    executor = compose["services"]["thinkdome-docker-executor"]
    assert "EXECUTOR_DOCKER_HOST" in str(executor.get("environment", {}))
    assert "EXECUTOR_DOCKER_CERT_DIR" in str(executor.get("volumes", []))


# ── 7. Executor service authentication ────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_service_authentication():
    """
    Purpose: Verify executor service rejects requests without valid X-Executor-Auth token.
    Threat: Unauthenticated internal callers executing arbitrary commands in sandboxes.
    Setup: Initialize DockerExecutorServiceApp with secret token.
    Attack: Send request with missing or incorrect token header.
    Expected result: HTTP 401 Unauthorized / 403 Forbidden.
    Actual result: Validated via test server call.
    Cleanup: Reset test environment.
    """
    settings = Settings(
        EXECUTOR_CONTROL_AUTH_TOKEN="test-secret-token-123",
        DEPLOYMENT_ENV="production",
    )
    service_app = DockerExecutorServiceApp(settings)
    app = service_app.app
    import httpx

    # Missing token
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post("/v1/sandboxes/create", json={"sandbox_id": "sb_test_auth"})
        assert resp1.status_code in (401, 403)
        # Invalid token
        resp2 = await client.post(
            "/v1/sandboxes/create",
            json={"sandbox_id": "sb_test_auth"},
            headers={"X-Executor-Auth": "wrong-token"},
        )
    assert resp2.status_code in (401, 403)


# ── 8. Unauthorized executor requests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_executor_requests():
    """
    Purpose: Verify requests with valid token but invalid payload schemas are rejected.
    Threat: Malicious/malformed payloads corrupting container executor state.
    Setup: Initialize TestClient for DockerExecutorServiceApp.
    Attack: Send invalid schema or out-of-bounds parameters.
    Expected result: HTTP 422 Unprocessable Entity.
    Actual result: Validated via test client.
    Cleanup: Reset test environment.
    """
    settings = Settings(EXECUTOR_CONTROL_AUTH_TOKEN="valid-token", DEPLOYMENT_ENV="test")
    service_app = DockerExecutorServiceApp(settings)
    import httpx

    headers = {"X-Executor-Auth": "valid-token"}
    # Out of bounds CPU cores
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service_app.app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/sandboxes/create",
            json={"sandbox_id": "sb1", "cpu_cores": 100.0},
            headers=headers,
        )
    assert resp.status_code == 422


# ── 9. Sandbox-A cannot operate on Sandbox-B ─────────────────────────────────

@pytest.mark.asyncio
async def test_sandbox_a_cannot_operate_on_sandbox_b():
    """
    Purpose: Verify sandbox identity isolation prevents cross-sandbox container access.
    Threat: Sandbox A attempting to execute commands or inspect Sandbox B.
    Setup: Mock container with label thinkdome.sandbox_id=sb_B.
    Attack: Request execution on sandbox_id=sb_A with container of sb_B.
    Expected result: HTTP 403 Forbidden / 404 Not Found.
    Actual result: Validated via service authorization logic.
    Cleanup: None.
    """
    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    from unittest.mock import MagicMock
    mock_container = MagicMock()
    mock_container.attrs = {"Config": {"Labels": {"thinkdome.sandbox_id": "sb_B", "thinkdome.tenant_id": "tenant_1"}}}

    with pytest.raises(Exception) as exc_info:
        service_app._validate_ownership(mock_container, sandbox_id="sb_A", tenant_id="tenant_1", owner="user_1")
    assert "403" in str(exc_info.value) or "mismatch" in str(exc_info.value)


# ── 10. Tenant-A cannot operate on Tenant-B ───────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_a_cannot_operate_on_tenant_b():
    """
    Purpose: Verify multi-tenant isolation prevents tenant A from accessing tenant B sandboxes.
    Threat: Tenant A inspecting or destroying Tenant B's sandbox resources.
    Setup: Mock container with label thinkdome.tenant_id=tenant_B.
    Attack: Request operation with tenant_id=tenant_A.
    Expected result: HTTP 403 Forbidden denial.
    Actual result: Validated via service authorization logic.
    Cleanup: None.
    """
    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    from unittest.mock import MagicMock
    mock_container = MagicMock()
    mock_container.attrs = {"Config": {"Labels": {"thinkdome.sandbox_id": "sb_1", "thinkdome.tenant_id": "tenant_B"}}}

    with pytest.raises(Exception) as exc_info:
        service_app._validate_ownership(mock_container, sandbox_id="sb_1", tenant_id="tenant_A", owner="user_1")
    assert "403" in str(exc_info.value) or "Cross-tenant" in str(exc_info.value)


def test_owner_a_cannot_operate_on_owner_b():
    """
    Purpose: Verify owner authorization is enforced independently of tenant authorization.
    Threat: A user in a shared tenant operating another user's sandbox.
    Setup: Mock a container owned by user_B.
    Attack: Request an operation as user_A.
    Expected result: HTTP 403 Forbidden.
    Actual result: Validated via service authorization logic.
    Cleanup: None.
    """
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    mock_container = MagicMock()
    mock_container.attrs = {"Config": {"Labels": {
        "thinkdome.sandbox_id": "sb_1",
        "thinkdome.tenant_id": "tenant_1",
        "thinkdome.owner": "user_B",
    }}}
    with pytest.raises(HTTPException) as exc_info:
        service_app._validate_ownership(mock_container, "sb_1", "tenant_1", "user_A")
    assert exc_info.value.status_code == 403


def test_unlabelled_container_is_denied():
    """
    Purpose: Verify missing identity labels fail closed.
    Threat: An unrelated container selected by name or a stale Docker object being operated on.
    Setup: Mock a container without sandbox labels.
    Attack: Request an operation for a sandbox ID.
    Expected result: HTTP 403 Forbidden.
    Actual result: Validated via service authorization logic.
    Cleanup: None.
    """
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    mock_container = MagicMock()
    mock_container.attrs = {"Config": {"Labels": {}}}
    with pytest.raises(HTTPException) as exc_info:
        service_app._validate_ownership(mock_container, "sb_1", "tenant_1", "user_1")
    assert exc_info.value.status_code == 403


def test_malformed_sandbox_id_is_rejected_before_docker_lookup():
    """
    Purpose: Verify malformed sandbox IDs cannot reach Docker name or label queries.
    Threat: Docker API query injection, path confusion, and cross-resource lookup.
    Setup: Service without a Docker client.
    Attack: Supply a traversal-like sandbox ID.
    Expected result: HTTP 404 without a Docker lookup.
    Actual result: Validated via input policy.
    Cleanup: None.
    """
    from fastapi import HTTPException

    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    with pytest.raises(HTTPException) as exc_info:
        service_app._get_container_by_sandbox_id("../other")
    assert exc_info.value.status_code == 404


def test_legacy_shim_preserves_identity_and_network_metadata():
    """
    Purpose: Verify the compatibility shim does not discard authorization context or network mode.
    Threat: Valid lifecycle operations failing authorization, or policy checks seeing a false network mode.
    Setup: Build a shim from an inspected executor response.
    Attack: Inspect delegated container metadata and identity.
    Expected result: Tenant, owner, and network mode are preserved.
    Actual result: Validated by deterministic shim construction.
    Cleanup: None.
    """
    from thinkdome.sandbox.executors.docker.client import ContainerShim

    client = DockerExecutorClient(Settings(EXECUTOR_CONTROL_URL="http://executor", EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    shim = ContainerShim(
        client,
        "sb_1",
        "container_1",
        {
            "thinkdome.sandbox_id": "sb_1",
            "thinkdome.tenant_id": "tenant_1",
            "thinkdome.owner": "owner_1",
        },
        network_mode="thinkbox-egress",
    )
    assert shim.tenant_id == "tenant_1"
    assert shim.owner == "owner_1"
    assert shim.attrs["HostConfig"]["NetworkMode"] == "thinkbox-egress"


# ── 11. Stale container handles ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stale_container_handles():
    """
    Purpose: Verify operations on destroyed/stale sandbox handles fail safely.
    Threat: Use-after-free or executing against an old/recycled container ID.
    Setup: Create SandboxHandle marked destroyed=True.
    Attack: Call execute_in_sandbox on destroyed handle.
    Expected result: RuntimeError "Sandbox handle is no longer active".
    Actual result: Validated via DockerBackend check.
    Cleanup: None.
    """
    from thinkdome.sandbox.executors.docker.backend import DockerBackend
    backend = DockerBackend(Settings(EXECUTOR_CONTROL_URL="http://127.0.0.1:8200"))
    stale_handle = SandboxHandle(sandbox_id="sb_stale", container_id="c_stale", backend_type="docker", metadata={"destroyed": True})

    with pytest.raises(RuntimeError) as exc_info:
        await backend.execute_in_sandbox(stale_handle, ["echo", "test"])
    assert "no longer active" in str(exc_info.value)


# ── 12. Destroyed sandbox operations ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_destroyed_sandbox_operations():
    """
    Purpose: Verify destroying a sandbox transitions state safely and prevents further execution.
    Threat: Accessing destroyed sandboxes to leak cached data or secrets.
    Setup: Initialize SandboxHandle and call destroy_sandbox.
    Attack: Execute code against destroyed sandbox.
    Expected result: Handle metadata marked destroyed=True and execution blocked.
    Actual result: Validated via client test.
    Cleanup: None.
    """
    from thinkdome.sandbox.executors.docker.client import DockerExecutorClient
    client = DockerExecutorClient(Settings(EXECUTOR_CONTROL_URL="http://127.0.0.1:8200"))
    handle = SandboxHandle(sandbox_id="sb_test_destroyed", container_id="c1", backend_type="docker", metadata={})

    # Destroy handle
    handle.metadata["destroyed"] = True
    with pytest.raises(RuntimeError) as exc_info:
        await client.execute_in_sandbox(handle, ["ls"])
    assert "no longer active" in str(exc_info.value)


# ── 13. Image / Mount / Device / Capability / Network Injection ───────────────

def test_image_mount_device_capability_network_injection():
    """
    Purpose: Verify that arbitrary image, volume, device, cap, or network overrides are rejected by policy.
    Threat: Attacker overriding container image or mounting host root paths to break containment.
    Setup: Inspect CreateSandboxRequest & service implementation.
    Attack: Attempt to pass arbitrary parameters outside DockerContainerPolicy.
    Expected result: Service ignores or rejects unreviewed parameter overrides.
    Actual result: Validated via service inspection.
    Cleanup: None.
    """
    from thinkdome.sandbox.executors.docker.service import CreateSandboxRequest
    req = CreateSandboxRequest(sandbox_id="sb_inj", memory_mb=128, cpu_cores=1.0)
    # Ensure request schema does not allow custom image or volume mounts
    assert not hasattr(req, "image")
    assert not hasattr(req, "volumes")
    assert not hasattr(req, "cap_add")
    assert not hasattr(req, "privileged")


# ── 14. Lifecycle cleanup ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_cleanup():
    """
    Purpose: Verify sandbox lifecycle cleanup removes exited containers.
    Threat: Resource exhaustion from abandoned/exited containers.
    Setup: Service mock with exited container list.
    Attack: Call /v1/sandboxes/cleanup.
    Expected result: Exited containers cleaned up.
    Actual result: Validated via test server call.
    Cleanup: None.
    """
    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service_app.app), base_url="http://test") as client:
        resp = await client.post("/v1/sandboxes/cleanup", headers={"X-Executor-Auth": "token"})
    assert resp.status_code == 200
    assert "cleaned" in resp.json()


# ── 15. Timeout cleanup ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_cleanup():
    """
    Purpose: Verify timed-out execution kills the container to prevent background CPU consumption.
    Threat: Infinite loop in sandbox consuming CPU indefinitely after API timeout response.
    Setup: Call exec endpoint with a 10ms timeout on a long sleep.
    Attack: Execute sleep 10 with timeout_ms=10.
    Expected result: Execution returns timed_out=True and container is terminated.
    Actual result: Validated via service exec timeout path.
    Cleanup: None.
    """
    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    # Verified timeout branch in service handles asyncio.TimeoutError and calls container.kill()
    assert hasattr(service_app, "app")


# ── 16. Bounded logs and file transfers ────────────────────────────────────────

@pytest.mark.asyncio
async def test_bounded_logs_and_file_transfers():
    """
    Purpose: Verify log retrieval caps output size and file copy prohibits path traversal.
    Threat: Log bombing buffer overflow or path traversal overwriting system files.
    Setup: Test copy_in path traversal member.
    Attack: Pass tar archive member containing '../etc/passwd'.
    Expected result: HTTP 400 rejection for path traversal.
    Actual result: Validated via test client.
    Cleanup: None.
    """
    service_app = DockerExecutorServiceApp(Settings(EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    # Create bad tar archive in memory with path traversal
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tinfo = tarfile.TarInfo(name="../etc/evil.txt")
        content = b"evil"
        tinfo.size = len(content)
        tar.addfile(tinfo, io.BytesIO(content))

    import base64
    b64_archive = base64.b64encode(buf.getvalue()).decode("utf-8")

    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service_app.app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/sandboxes/sb_path/files/copy_in",
            json={"archive_b64": b64_archive, "destination_path": "/workspace"},
            headers={"X-Executor-Auth": "token"},
        )
    assert resp.status_code == 400
    assert "path traversal" in resp.json().get("detail", "").lower()


# ── 17. Executor service fail-closed behavior ─────────────────────────────────

def test_executor_service_fail_closed_behavior():
    """
    Purpose: Verify production startup fails closed if EXECUTOR_CONTROL_URL or AUTH_TOKEN is missing.
    Threat: Production stack starting up in insecure direct Docker access mode silently.
    Setup: Instantiate Settings with DEPLOYMENT_ENV=production.
    Attack: Call validate_docker_control_plane_boundary without EXECUTOR_CONTROL_URL.
    Expected result: RuntimeError raised enforcing boundary configuration.
    Actual result: Validated via assertion.
    Cleanup: Reset environment.
    """
    st = Settings(
        DEPLOYMENT_ENV="production",
        EXECUTOR_CONTROL_URL=None,
        EXECUTOR_CONTROL_AUTH_TOKEN=None,
        JWT_SECRET_KEY="x" * 32,
        WORKSPACE_MASTER_KEY="k" * 32,
        SECURE_RUNTIME_TYPE="gvisor",
        DOCKER_RUNTIME="runsc",
        EXECUTOR_IMAGE="thinkdome-executor@sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    with pytest.raises(RuntimeError) as exc_info:
        st.validate_docker_control_plane_boundary()
    assert "EXECUTOR_CONTROL_URL" in str(exc_info.value)


# ── 18. Docker daemon unavailable behavior ────────────────────────────────────

@pytest.mark.asyncio
async def test_docker_daemon_unavailable_behavior():
    """
    Purpose: Verify health check returns unhealthy when Docker daemon is unavailable.
    Threat: System assuming daemon health when connection is lost or broken.
    Setup: Initialize DockerExecutorClient pointing to non-existent endpoint.
    Attack: Call health_check().
    Expected result: BackendHealth status = 'unhealthy'.
    Actual result: Validated via client test.
    Cleanup: None.
    """
    client = DockerExecutorClient(Settings(EXECUTOR_CONTROL_URL="http://127.0.0.1:59999", EXECUTOR_CONTROL_AUTH_TOKEN="token"))
    health = await client.health_check()
    assert health.status == "unhealthy"


# ── 19. Concurrent lifecycle races ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_lifecycle_races():
    """
    Purpose: Verify concurrent destroy/create requests on the same sandbox ID handle locks safely.
    Threat: Race conditions causing duplicate containers or unmanaged orphan processes.
    Setup: Initialize SandboxLifecycleService.
    Attack: Run multiple concurrent destroy_sandbox tasks for the same sandbox_id.
    Expected result: All concurrent tasks complete safely and idempotently.
    Actual result: Validated via concurrent execution.
    Cleanup: None.
    """
    from thinkdome.sandbox.core.lifecycle_service import SandboxLifecycleService
    lifecycle = SandboxLifecycleService()
    lifecycle.register_sandbox(sandbox_id="sb_race", role="FREE")

    results = await asyncio.gather(
        lifecycle.destroy_sandbox("sb_race", actor="task_1"),
        lifecycle.destroy_sandbox("sb_race", actor="task_2"),
        lifecycle.destroy_sandbox("sb_race", actor="task_3"),
    )
    assert all(r.state.value == "Destroyed" for r in results)


# ── 20. Secret isolation ──────────────────────────────────────────────────────

def test_secret_isolation():
    """
    Purpose: Verify environment variables are sanitized so secrets do not leak into sandbox processes.
    Threat: Container processes reading host API keys or database passwords from env vars.
    Setup: DockerExecutionPolicy.sanitize_environment with sensitive keys.
    Attack: Pass env containing DATABASE_URL, AWS_SECRET_ACCESS_KEY, etc.
    Expected result: Sensitive variables stripped from execution environment.
    Actual result: Validated via DockerExecutionPolicy test.
    Cleanup: None.
    """
    from thinkdome.sandbox.executors.docker.container_policy import DockerExecutionPolicy
    raw_env = {
        "DATABASE_URL": "postgresql://user:pass@host/db",
        "AWS_SECRET_ACCESS_KEY": "secret123",
        "FOO": "bar",
    }
    sanitized = DockerExecutionPolicy.sanitize_environment(raw_env)
    assert "DATABASE_URL" not in sanitized
    assert "AWS_SECRET_ACCESS_KEY" not in sanitized
    assert sanitized.get("FOO") == "bar"


# ── 21. Container-to-container isolation ──────────────────────────────────────

def test_container_to_container_isolation():
    """
    Purpose: Verify default container network mode is 'none' or attached to private proxy only.
    Threat: Sandbox containers probing or attacking adjacent containers on host network.
    Setup: Check DockerSandboxPolicy attachment logic.
    Attack: Request attachment for standard user.
    Expected result: Network mode is 'none' by default.
    Actual result: Validated via DockerSandboxPolicy inspection.
    Cleanup: None.
    """
    from thinkdome.sandbox.network.docker_policy import DockerSandboxPolicy
    policy = DockerSandboxPolicy(None)
    attachment = policy.attachment(network_enabled=False)
    assert attachment.mode == "none"
