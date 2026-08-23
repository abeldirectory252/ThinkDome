"""Security-sensitive configuration defaults and parsing."""

import pytest

from thinkdome.core.config import Settings
from thinkdome.security.api.admin import CreateSandboxRequest
from thinkdome.platform.storage.filebox.service import FileBoxService
from thinkdome.platform.storage.workspaces.service import WorkspaceService
from thinkdome.platform.storage.workspaces.models import CreateWorkspaceRequest
from thinkdome.sandbox.core.models import FileInput
from thinkdome.sandbox.core.models import ExecuteRequest
from thinkdome.sandbox.sessions.models import CreateSessionRequest
from thinkdome.platform.storage.api.filebox import FileBoxCreateRequest, FileBoxProvisionRequest
from thinkdome.api.routes.control_plane import PlacementRequest
from thinkdome.security.api.auth import register


def test_cors_is_disabled_by_default():
    assert Settings(CORS_ALLOW_ORIGINS="").cors_allow_origins() == []


def test_cors_accepts_only_explicit_origins():
    settings = Settings(CORS_ALLOW_ORIGINS="https://console.example, https://app.example ")
    assert settings.cors_allow_origins() == ["https://console.example", "https://app.example"]


def test_host_subprocess_fallback_is_never_available_in_production():
    assert not Settings(
        DEPLOYMENT_ENV="production", EXECUTOR_BACKEND_USE_FALLBACK=True
    ).allows_insecure_execution_fallback()
    assert Settings(
        DEPLOYMENT_ENV="development", EXECUTOR_BACKEND_USE_FALLBACK=True
    ).allows_insecure_execution_fallback()


def test_production_rejects_host_subprocess_backend():
    with pytest.raises(RuntimeError, match="subprocess execution backend"):
        Settings(DEPLOYMENT_ENV="production", EXECUTOR_BACKEND="subprocess").validate_production_runtime()


def test_production_requires_immutable_docker_image():
    with pytest.raises(RuntimeError, match="immutable"):
        Settings(DEPLOYMENT_ENV="production", EXECUTOR_BACKEND="docker", EXECUTOR_IMAGE="runner:latest").validate_production_runtime()


def test_production_requires_explicit_hardened_runtime():
    with pytest.raises(RuntimeError, match="hardened sandbox runtime"):
        Settings(
            DEPLOYMENT_ENV="production",
            EXECUTOR_BACKEND="docker",
            EXECUTOR_IMAGE="runner@sha256:" + "a" * 64,
            SECURE_RUNTIME_TYPE="",
        ).validate_production_runtime()


def test_production_rejects_plain_docker_runtime():
    with pytest.raises(RuntimeError, match="gvisor or kata"):
        Settings(
            DEPLOYMENT_ENV="production",
            EXECUTOR_BACKEND="docker",
            EXECUTOR_IMAGE="runner@sha256:" + "a" * 64,
            SECURE_RUNTIME_TYPE="microvm",
        ).validate_production_runtime()


@pytest.mark.parametrize(
    "field,value",
    [("memory_mb", 0), ("memory_mb", 65537), ("cpu_cores", 0), ("cpu_cores", 65),
     ("timeout_sec", 0), ("timeout_sec", 86401)],
)
def test_sandbox_resources_are_bounded(field, value):
    with pytest.raises(ValueError):
        CreateSandboxRequest(name="bounded", **{field: value})


@pytest.mark.parametrize("tenant,owner", [("../escape", "alice"), ("tenant", "../../etc"), ("tenant/x", "alice")])
def test_filebox_namespace_rejects_path_traversal(tenant, owner):
    with pytest.raises(ValueError, match="namespace component"):
        FileBoxService._validate_namespace(tenant, owner)


def test_workspace_records_are_owner_scoped(tmp_path):
    settings = Settings(FILE_STORAGE_DIR=str(tmp_path))
    service = WorkspaceService(settings)
    workspace = service.create(CreateWorkspaceRequest(name="private"), owner_id="alice")
    assert service.get(workspace.workspace_id, "alice") is not None
    assert service.get(workspace.workspace_id, "bob") is None
    assert service.list_workspaces("bob") == []


@pytest.mark.parametrize("path", ["../escape.py", "/etc/passwd", "a/../../escape", "./script.py"])
def test_execution_file_paths_cannot_escape_workspace(path):
    with pytest.raises(ValueError, match="file path"):
        FileInput(path=path)


@pytest.mark.parametrize("key", ["LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS"])
def test_execution_rejects_interpreter_injection_environment(key):
    from thinkdome.sandbox.core.models import ExecuteRequest

    with pytest.raises(ValueError, match="environment variable"):
        ExecuteRequest(code="print(1)", env_vars={key: "attacker-value"})


def test_host_workspace_namespace_cannot_use_username_as_path():
    from thinkdome.sandbox.executors.host.subprocess_executor import SubprocessExecutor

    executor = SubprocessExecutor()
    path = executor._get_user_workspace("../../escape")
    assert path is not None
    assert path.name != "escape"
    assert path.parent.name == "workspaces"


@pytest.mark.parametrize("language", ["../python", "/tmp", "python\x00", "python.lang"])
def test_execution_language_cannot_be_used_for_path_construction(language):
    with pytest.raises(ValueError, match="language"):
        ExecuteRequest(code="print(1)", language=language)
    with pytest.raises(ValueError, match="language"):
        CreateSessionRequest(language=language)


def test_filebox_payload_and_tenant_identifiers_are_bounded():
    with pytest.raises(ValueError):
        FileBoxCreateRequest(filename="a", content_base64="x" * 67_108_865)
    with pytest.raises(ValueError):
        FileBoxProvisionRequest(username="alice", tenant_id="../../escape")


def test_control_plane_placement_resources_are_bounded():
    with pytest.raises(ValueError):
        PlacementRequest(project_id="p", sandbox_id="s", memory_bytes=68_719_476_737)
    with pytest.raises(ValueError):
        PlacementRequest(project_id="p", sandbox_id="s", cpu_millis=256_001)
    with pytest.raises(ValueError):
        PlacementRequest(project_id="../p", sandbox_id="s")


def test_public_registration_cannot_select_privileged_role():
    import inspect
    source = inspect.getsource(register)
    assert 'role="AGENT_STANDARD"' in source
    assert 'credentials.role' not in source


def test_production_rejects_default_infrastructure_credentials():
    with pytest.raises(RuntimeError, match="default credentials"):
        Settings(
            DEPLOYMENT_ENV="production",
            EXECUTOR_BACKEND="docker",
            EXECUTOR_IMAGE="runner@sha256:" + "a" * 64,
            SECURE_RUNTIME_TYPE="gvisor",
            WORKSPACE_MASTER_KEY="x" * 32,
            DATABASE_URL="postgresql://thinkdome:thinkdome@db:5432/thinkdome",
            RABBITMQ_URL="amqp://guest:guest@rabbitmq:5672/",
        ).validate_production_runtime()


def test_legacy_login_does_not_hardcode_admin_role():
    from pathlib import Path
    source = Path("thinkdome/security/auth/service.py").read_text()
    assert '"role": "ADMIN",  # Dashboard admin access' not in source


def test_api_key_identity_has_unique_workspace_namespace():
    from pathlib import Path
    source = Path("thinkdome/security/auth/service.py").read_text()
    assert '"workspace_id": f"api_key_' in source


def test_vault_ownership_does_not_trust_user_header():
    from pathlib import Path
    source = Path("thinkdome/security/api/vault.py").read_text()
    assert "user_id=x_user_id" not in source
    assert "owner_id = str(user.get" in source


def test_non_admin_sandbox_owners_are_not_global():
    from thinkdome.security.identity.core import UserIdentity, RolePolicyEngine
    user = UserIdentity.from_dict({"username": "alice", "role": "AGENT_STANDARD"})
    assert not RolePolicyEngine.is_sandbox_accessible({"owner": "api_key_client"}, user)
    assert not RolePolicyEngine.is_sandbox_accessible({"owner": "anonymous"}, user)


def test_api_key_workspace_namespace_remains_accessible_to_that_key():
    from thinkdome.security.identity.core import UserIdentity, RolePolicyEngine
    identity = UserIdentity.from_dict({
        "username": "api_key_client",
        "role": "SDK",
        "key_id": "key_123",
        "workspace_id": "api_key_key_123",
    })
    assert RolePolicyEngine.is_sandbox_accessible({"owner": "api_key_key_123"}, identity)


def test_dynamic_records_use_workspace_namespace_and_protect_owner_field():
    from pathlib import Path
    source = Path("thinkdome/core/api/router.py").read_text()
    assert "user.get(\"workspace_id\", user.get(\"username\"))" in source
    assert 'if k == "owner" and user.get("role") != "ADMIN":' in source


def test_storage_tools_use_identity_workspace_namespace():
    from pathlib import Path
    source = Path("thinkdome/platform/storage/tools/storage_tools.py").read_text()
    assert "metadata.get(\"workspace_id\")" in source


def test_execution_tools_use_identity_workspace_namespace():
    from pathlib import Path
    source = Path("thinkdome/sandbox/tools/execution_tools.py").read_text()
    assert "metadata.get(\"workspace_id\")" in source
    assert "inject_into_env(owner" in source


def test_mcp_uses_identity_workspace_namespace():
    from pathlib import Path
    source = Path("thinkdome/platform/orchestration/mcp_server.py").read_text()
    assert 'identity.metadata.get("workspace_id")' in source


def test_orchestrator_uses_identity_workspace_namespace():
    from pathlib import Path
    source = Path("thinkdome/platform/orchestration/api.py").read_text()
    assert 'current_user.get("workspace_id"' in source


def test_registration_usernames_cannot_escape_workspace_paths():
    from thinkdome.security.api.auth import UserCredentials
    with pytest.raises(ValueError):
        UserCredentials(username="../../escape", password="password")


def test_docker_persistent_workspace_names_are_hashed():
    from pathlib import Path
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "hashlib.sha256(str(username).encode" in source


def test_production_requires_strong_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT signing secret"):
        Settings(
            DEPLOYMENT_ENV="production",
            EXECUTOR_BACKEND="docker",
            EXECUTOR_IMAGE="runner@sha256:" + "a" * 64,
            SECURE_RUNTIME_TYPE="gvisor",
            WORKSPACE_MASTER_KEY="x" * 32,
            DATABASE_URL="postgresql://user:strong@db/thinkdome",
            RABBITMQ_URL="amqp://user:strong@mq/thinkdome",
        ).validate_production_runtime()


def test_admin_bootstrap_assigns_role_through_rbac():
    from pathlib import Path
    source = Path("thinkdome/security/api/auth.py").read_text()
    service_source = Path("thinkdome/security/auth/service.py").read_text()
    assert 'self.register("admin", "admin123", role="ADMIN")' in service_source
    assert 'username in {"admin", "administrator"}' not in source


def test_jwt_role_is_taken_from_rbac_rehydration():
    from pathlib import Path
    source = Path("thinkdome/security/auth/service.py").read_text()
    assert 'role = resolved_role' in source
