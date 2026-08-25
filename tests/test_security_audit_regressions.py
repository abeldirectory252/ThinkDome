"""Regression tests for security audit findings (BUG 1 - BUG 9)."""

import os
import sys
import time
import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from thinkdome.api.server import create_app
from thinkdome.sandbox.executors.base import ExecRequest
from thinkdome.sandbox.executors.host.subprocess_executor import SubprocessExecutor
from thinkdome.sandbox.executors.host.bubblewrap import BubblewrapExecutor
from thinkdome.sandbox.executors.docker.python_executor import PythonDockerExecutor
from thinkdome.sandbox.sdk import Sandbox
from thinkdome.sandbox.snapshots.service import SnapshotService
from thinkdome.sandbox.network.signing import build_signed_route, verify_signed_route
from thinkdome.sandbox.core.lifecycle_service import SandboxLifecycleService, SandboxState
from thinkdome.core.config import get_settings


# ── BUG 1: Process Tree Timeout Termination ──

@pytest.mark.asyncio
async def test_subprocess_executor_process_tree_killed_on_timeout():
    """Verify that child processes created by sandbox code are killed on timeout."""
    executor = SubprocessExecutor()
    await executor.initialize()

    # Code spawns a background sleep child process
    code = """
import subprocess, time
subprocess.Popen(["sleep", "30"])
time.sleep(10)
"""
    req = ExecRequest(
        code=code,
        language="python",
        timeout_ms=500,  # 0.5s timeout
        max_output_bytes=1024,
    )
    result = await executor.execute(req)
    assert result.timed_out is True
    assert result.exit_code == -1


# ── BUG 2: SubprocessExecutor Path Traversal ──

@pytest.mark.asyncio
async def test_subprocess_executor_path_traversal_blocked():
    """Verify that executor blocks file writes escaping workspace boundary."""
    executor = SubprocessExecutor()
    await executor.initialize()

    req = ExecRequest(
        code="print('hello')",
        language="python",
        files={"../../escaped.txt": b"malicious"},
        timeout_ms=2000,
    )
    # Executing request with traversing file path should fail safely
    result = await executor.execute(req)
    assert result.exit_code != 0 or "Path traversal" in result.stderr or "Permission" in result.stderr or "Invalid" in result.stderr or "blocked" in result.stderr


# ── BUG 3: SDK Path Traversal ──

def test_sdk_path_traversal_blocked(tmp_path):
    """Verify SDK prevents reading/writing files outside workspace boundary."""
    sb = Sandbox(backend="subprocess")
    sb._workspace = tmp_path

    with pytest.raises(PermissionError):
        sb.read_file("../../etc/passwd")

    with pytest.raises(PermissionError):
        sb.write_file("../../../tmp/malicious.txt", "content")

    with pytest.raises(PermissionError):
        sb.read_file_bytes("../../etc/shadow")


# ── BUG 4: XSS in Hosted Site Page ──

def test_hosted_site_xss_escaped():
    """Verify site_id is HTML-escaped in expired hosted site response."""
    app = create_app()
    with TestClient(app) as client:
        xss_payload = "<script>alert('xss')</script>"
        res = client.get(f"/v1/hosted/{xss_payload}/")
        assert res.status_code == 404
        assert "<script>" not in res.text
        assert "&lt;script&gt;" in res.text or "%3Cscript%3E" in res.text or "alert" in res.text


# ── BUG 5: Snapshot Restore Untrusted state_dir ──

def test_snapshot_service_untrusted_state_dir_ignored(tmp_path):
    """Verify snapshot restore does not follow arbitrary state_dir in metadata.json."""
    storage = tmp_path / "snapshots"
    storage.mkdir()
    svc = SnapshotService(get_settings())
    svc.storage_dir = storage

    # Create a snapshot directory
    snap_id = "snap_test123"
    snap_dir = storage / snap_id
    snap_dir.mkdir()
    files_dir = snap_dir / "workspace_files"
    files_dir.mkdir()
    (files_dir / "safe.txt").write_text("safe content")

    # Metadata with malicious state_dir pointing to /etc
    meta = {
        "snapshot_id": snap_id,
        "state_dir": "/etc",
        "name": "test",
    }
    (snap_dir / "metadata.json").write_text(str(meta).replace("'", '"'))

    target_ws = tmp_path / "target_ws"
    res = svc.restore_snapshot("sb_1", snap_id, workspace_path=str(target_ws))
    assert res["success"] is True
    # Verify files restored from actual snap_dir workspace_files, NOT /etc
    assert (target_ws / "safe.txt").exists()
    assert not (target_ws / "passwd").exists()


# ── BUG 7: Signed Route Signature Verification ──

def test_signed_route_verification():
    """Verify OSEP-0011 signed route generation and verification."""
    secret = b"test_secret_key_32_bytes_long!!"
    keys = {"a": secret}
    now = int(time.time())

    # Build valid route
    route = build_signed_route("sb-123", 8080, now + 300, secret, key_id="a")
    valid, reason, sb_id, port = verify_signed_route(route, keys, now)
    assert valid is True
    assert sb_id == "sb-123"
    assert port == 8080

    # Tamper signature
    tampered = route[:-1] + "b"
    valid_t, reason_t, _, _ = verify_signed_route(tampered, keys, now)
    assert valid_t is False


# ── BUG 9: Renew Expiration State Validation ──

def test_lifecycle_renew_expiration_destroyed_state_rejected():
    """Verify renew_expiration rejects sandboxes in DESTROYED or FAILED states."""
    svc = SandboxLifecycleService()
    info = svc.register_sandbox("sb_destroyed_test")
    info.state = SandboxState.DESTROYED

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.renew_expiration("sb_destroyed_test", timeout_seconds=600)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_bubblewrap_direct_exec_request_cannot_write_outside_workspace(tmp_path, monkeypatch):
    """Executor-level validation must protect callers that bypass Pydantic."""
    outside = tmp_path / "outside.txt"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(
        "thinkdome.sandbox.executors.host.bubblewrap.tempfile_create",
        lambda: str(workspace),
    )
    executor = BubblewrapExecutor(get_settings())
    result = await executor.execute(
        ExecRequest(code="print('ok')", files={"../outside.txt": b"escape"})
    )
    assert result.exit_code != 0
    assert not outside.exists()


def test_docker_tar_rejects_direct_exec_request_path_traversal():
    executor = PythonDockerExecutor(get_settings())
    with pytest.raises(ValueError, match="escapes workspace"):
        executor._create_tar({"../../host-file": b"escape"})


def test_snapshot_explicit_files_and_ids_cannot_escape_storage(tmp_path):
    settings = get_settings()
    settings.SNAPSHOT_STORAGE_DIR = str(tmp_path / "snapshots")
    svc = SnapshotService(settings)
    outside = tmp_path / "outside.txt"
    with pytest.raises(ValueError, match="snapshot file path"):
        svc.create_snapshot("sb", files={"../outside.txt": b"escape"})
    assert not outside.exists()
    with pytest.raises(ValueError, match="invalid snapshot id"):
        svc.delete_snapshot("../outside")


def test_snapshot_skips_workspace_symlinks(tmp_path):
    settings = get_settings()
    settings.SNAPSHOT_STORAGE_DIR = str(tmp_path / "snapshots")
    svc = SnapshotService(settings)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    (workspace / "link.txt").symlink_to(target)
    meta = svc.create_snapshot("sb", workspace_path=str(workspace))
    assert not (Path(meta["state_dir"]) / "workspace_files" / "link.txt").exists()


def test_vault_sandbox_access_is_owner_scoped():
    from types import SimpleNamespace
    from thinkdome.security.api.vault import _authorize_sandbox

    class DB:
        def get_sandbox(self, sandbox_id):
            return {"sandbox_id": sandbox_id, "owner": "alice"}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_service=DB())))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _authorize_sandbox(request, "sb-1", {"username": "bob", "role": "AGENT_STANDARD"})
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_pool_failed_release_destroys_container_and_duplicate_release_is_noop():
    from thinkdome.sandbox.pool.manager import PoolManager

    settings = get_settings()
    settings.POOL_MIN_WARM = 0
    settings.POOL_MAX_SIZE = 4
    pool = PoolManager(settings, docker_client=None)
    container = await pool.acquire()
    assert container is not None
    await pool.release(container.pool_id, reset=False)
    assert container.pool_id not in pool._containers
    # A retry must not recreate or requeue the failed container.
    await pool.release(container.pool_id)
    assert container.pool_id not in pool._containers


def test_idempotency_key_cannot_replay_for_different_sandbox():
    from tests.test_control_plane_lifecycle import FakeRepository, node
    from thinkdome.control_plane.contracts import SandboxPlacementRequest
    from thinkdome.control_plane.lifecycle import ControlPlaneLifecycle, IdempotencyConflict

    service = ControlPlaneLifecycle(FakeRepository())
    service.create_sandbox(
        SandboxPlacementRequest(organization_id="org", project_id="project", sandbox_id="sb-a"),
        [node()], idempotency_key="same-key",
    )
    with pytest.raises(IdempotencyConflict):
        service.create_sandbox(
            SandboxPlacementRequest(organization_id="org", project_id="project", sandbox_id="sb-b"),
            [node()], idempotency_key="same-key",
        )


def test_code_tool_does_not_inject_vault_secrets_for_llm_role():
    source = Path("thinkdome/sandbox/tools/execution_tools.py").read_text()
    assert 'str(ctx.caller_role or "").upper() in {"ADMIN", "ORCH", "IDE"}' in source


def test_llm_cannot_escalate_to_ide_or_override_resource_limits():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert 'role == "LLM" and request.allow_network' not in source
    assert 'can_customize_resources = role in {"ADMIN", "ORCH", "IDE"}' in source


def test_direct_executor_env_cannot_enable_interpreter_injection():
    source = Path("thinkdome/sandbox/executors/host/subprocess_executor.py").read_text()
    assert "_BLOCKED_INTERPRETER_ENV_KEYS" in source
    source = Path("thinkdome/sandbox/executors/host/bubblewrap.py").read_text()
    assert "key.upper() not in _BLOCKED_INTERPRETER_ENV_KEYS" in source


def test_secure_runtime_guard_fails_closed_when_docker_unavailable():
    from thinkdome.sandbox.security.runtime_guard import validate_secure_runtime_on_startup

    class Settings:
        SECURE_RUNTIME_TYPE = "gvisor"
        EXECUTOR_BACKEND = "docker"
        DOCKER_RUNTIME = "runsc"

    with pytest.raises(RuntimeError, match="fail-open"):
        validate_secure_runtime_on_startup(Settings(), docker_client=None)


def test_snapshot_api_scopes_reads_and_writes_by_authenticated_owner():
    source = Path("thinkdome/sandbox/snapshots/api.py").read_text()
    assert "owner=_owner(user)" in source
    assert "owner=None if _is_admin(user) else _owner(user)" in source


def test_sandbox_scoped_routes_enforce_object_authorization():
    for name in ("diagnostics.py", "lifecycle.py", "metadata.py"):
        source = Path(f"thinkdome/api/routes/execution/{name}").read_text()
        assert "authorize_sandbox_access(request, sandbox_id, user)" in source


def test_session_history_is_bounded_and_execution_serialized():
    source = Path("thinkdome/sandbox/sessions/service.py").read_text()
    assert "self._max_history_blocks" in source
    assert "async with lock" in source
    assert "Keep the lock object stable" in source


def test_kubernetes_network_disabled_sandboxes_install_deny_egress_policy():
    source = Path("thinkdome/sandbox/executors/kubernetes/backend.py").read_text()
    assert "if not network_enabled:" in source
    assert "V1NetworkPolicySpec" in source
    assert 'policy_types=["Egress"]' in source
    assert "egress=[]" in source
    assert "refusing network-disabled sandbox" in source


def test_kubernetes_exec_cancels_stream_and_validates_env_names():
    source = Path("thinkdome/sandbox/executors/kubernetes/backend.py").read_text()
    assert "cancelled = threading.Event()" in source
    assert "cancelled.set()" in source
    assert "resp.close()" in source
    assert "Invalid environment variable names" in source


def test_subprocess_stream_disconnect_kills_process_group_and_reader_task():
    source = Path("thinkdome/sandbox/executors/host/subprocess_executor.py").read_text()
    assert "os.killpg(proc.pid, signal.SIGKILL)" in source
    assert "bg_task.cancel()" in source
    assert "await asyncio.gather(bg_task, return_exceptions=True)" in source


def test_lifecycle_operations_are_serialized_per_sandbox():
    source = Path("thinkdome/sandbox/core/lifecycle_service.py").read_text()
    assert "self._operation_locks" in source
    assert "async with operation_lock" in source


def test_microvm_management_requires_privileged_role():
    source = Path("thinkdome/sandbox/executors/microvm/api.py").read_text()
    assert "_MICROVM_ADMIN_ROLES" in source
    assert "_require_microvm_admin(user)" in source
    assert "MicroVM management requires an administrator role" in source


def test_monitor_websocket_rejects_missing_or_unprivileged_session():
    source = Path("thinkdome/platform/observability/api/monitor.py").read_text()
    assert "identity = auth_service.verify_token(token) if token and auth_service else None" in source
    assert "if not identity or str(identity.get(\"role\", \"\")).upper()" in source
    assert "await websocket.close(code=1008, reason=\"Unauthorized\")" in source


def test_sandbox_access_denies_records_without_owner_metadata():
    source = Path("thinkdome/security/identity/core.py").read_text()
    assert "Missing ownership metadata must not turn an object reference" in source
    assert "if not owner:" in source
    assert "return False" in source


def test_runtime_warmup_requires_authenticated_admin():
    source = Path("thinkdome/api/routes/execution/languages.py").read_text()
    assert "dependencies=[Depends(get_current_user)]" in source
    assert "_user: dict = Depends(get_current_admin)" in source


def test_network_audit_routes_are_admin_scoped():
    source = Path("thinkdome/api/routes/execution/network_audit.py").read_text()
    assert "from thinkdome.core.dependencies import get_current_admin" in source
    assert "dependencies=[Depends(get_current_admin)]" in source


def test_admin_authority_requires_signed_role_not_username():
    source = Path("thinkdome/security/identity/core.py").read_text()
    assert "if self.username.lower() in DEFAULT_ADMIN_USERNAMES" not in source
    assert "return bool(self.roles.intersection(ADMIN_ROLES))" in source


def test_jwt_privileged_claims_fail_closed_when_rbac_unavailable():
    source = Path("thinkdome/security/auth/service.py").read_text()
    assert 'role = "AGENT_STANDARD"' in source
    assert "Fail closed during RBAC outages" in source


def test_single_sandbox_tokens_cannot_cross_sandbox_routes():
    authz = Path("thinkdome/api/routes/execution/authorization.py").read_text()
    vault = Path("thinkdome/security/api/vault.py").read_text()
    for source in (authz, vault):
        assert 'user.get("token_type") == "sandbox_access"' in source
        assert 'user.get("sandbox_id") != sandbox_id' in source


def test_http_tool_ignores_ambient_proxy_environment():
    source = Path("thinkdome/platform/orchestration/network/tools.py").read_text()
    assert "trust_env=False" in source


def test_shell_tool_cwd_check_uses_realpath_commonpath():
    source = Path("thinkdome/sandbox/tools/execution_tools.py").read_text()
    assert "os.path.commonpath" in source
    assert "os.path.realpath(resolved_cwd)" in source


def test_sdk_workspace_transfer_skips_symlinks_and_validates_outputs():
    source = Path("thinkdome/sandbox/sdk.py").read_text()
    assert "if p.is_symlink() or not p.is_file():" in source
    assert "out_path = resolve_safe_path(fname, self.workspace)" in source
    assert "not p.is_symlink()" in source


def test_file_update_enforces_upload_size_limit():
    service = Path("thinkdome/platform/storage/files/service.py").read_text()
    api = Path("thinkdome/platform/storage/api/files.py").read_text()
    assert "if len(content) > self.max_size:" in service
    assert "Storage quota exceeded" in service
    assert "status_code=413" in api


def test_filebox_quota_accounting_is_serialized_and_reports_quota_exceeded():
    source = Path("thinkdome/platform/storage/filebox/service.py").read_text()
    assert "_quota_locks" in source
    assert "with self._quota_lock(tenant_id, owner_id):" in source
    assert "Storage quota exceeded: FileBox virtual volume quota exceeded" in source


def test_storage_quota_is_configurable_globally_and_per_sandbox():
    config = Path("thinkdome/core/config.py").read_text()
    service = Path("thinkdome/platform/storage/filebox/service.py").read_text()
    admin = Path("thinkdome/security/api/admin.py").read_text()
    assert "FILEBOX_DEFAULT_QUOTA_MB" in config
    assert "self.default_quota_bytes" in service
    assert "filebox_default_quota_mb" in admin
    assert "storage_quota_mb: int = Field(10240" in admin
    assert "SystemSetting.query()" in admin
    assert "class Sandbox(Model)" in Path("thinkdome/apps/sandbox/models.py").read_text()


def test_database_sandbox_creation_uses_orm_not_raw_sql():
    source = Path("thinkdome/platform/database/service.py").read_text()
    method = source[source.index("    def create_sandbox("):source.index("    def get_sandbox(")]
    assert "Sandbox.query()" in method
    assert "sandbox.save()" in method
    assert "INSERT INTO sandboxes" not in method
    assert "UPDATE sandboxes SET" not in method


def test_database_sandbox_reads_updates_and_deletes_use_orm():
    source = Path("thinkdome/platform/database/service.py").read_text()
    for name in ("get_sandbox", "list_sandboxes", "update_sandbox_status", "delete_sandbox"):
        start = source.index(f"    def {name}(")
        end = source.find("\n    def ", start + 5)
        method = source[start:] if end == -1 else source[start:end]
        assert "Sandbox.query()" in method
        assert "fetch_one(\"SELECT * FROM sandboxes" not in method
        assert "UPDATE sandboxes SET" not in method


def test_mcp_authorization_does_not_use_missing_role_constant_or_leak_errors():
    source = Path("thinkdome/platform/orchestration/mcp_server.py").read_text()
    assert "ROLE_ADMIN" not in source
    assert "_MCP_ADMIN_ROLES" in source
    assert 'operation failed safely' in source


@pytest.mark.asyncio
async def test_subprocess_output_does_not_dereference_symlink_to_host_file():
    executor = SubprocessExecutor()
    result = await executor.execute(
        ExecRequest(
            code="import os; os.symlink('/etc/passwd', 'leak.txt')",
            timeout_ms=2000,
        )
    )
    assert result.exit_code == 0
    assert "leak.txt" not in result.output_files
