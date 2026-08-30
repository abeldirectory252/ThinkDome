"""Regression tests for Docker startup failures and secure network isolation."""

import json
from pathlib import Path

from thinkdome.core.config import Settings
from thinkdome.core.error_codes import SandboxErrorCodes
from thinkdome.sandbox.executors.base import ExecRequest
from thinkdome.sandbox.executors.docker.python_executor import PythonDockerExecutor
from thinkdome.sandbox.executors.docker.container_policy import DockerContainerPolicy


_NETNS_ERROR = (
    '500 Server Error: Internal Server Error ('
    '"bind-mount /proc/1044816/ns/net -> '
    '/var/run/docker/netns/a65ffff87c4a: no such file or directory")'
)


class _StartFailsWithNetnsMount:
    def start(self):
        from docker.errors import APIError

        raise APIError(_NETNS_ERROR)

    def remove(self, force=False):
        pass


class _Containers:
    def __init__(self):
        self.create_calls = []

    def create(self, **config):
        self.create_calls.append(config)
        return _StartFailsWithNetnsMount()


class _Client:
    def __init__(self):
        self.containers = _Containers()


def test_netns_mount_failure_does_not_weaken_network_isolation():
    """A daemon netns failure must not retry with host or bridge networking."""
    executor = PythonDockerExecutor(Settings())
    executor.client = _Client()

    result = executor._execute_sync(ExecRequest(code="print('test')", caller_role="LLM"))

    assert result.exit_code == 1
    assert result.error_code == SandboxErrorCodes.DOCKER_NETNS_SETUP_FAILED
    assert "Docker could not create the sandbox network namespace" in result.stderr


def test_docker_backend_never_falls_back_to_bridge_networking():
    source = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert 'network_mode="none" if not network_enabled else "bridge"' not in source
    policy = Path("thinkdome/sandbox/network/docker_policy.py").read_text()
    assert 'PROXY_NETWORK = "thinkbox-egress"' in policy
    assert "Approved egress network" in policy
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert "validate_secure_runtime_on_startup" in backend
    assert "runtime=runtime" in backend
    assert "enforce_environment" in backend
    policy = Path("thinkdome/sandbox/network/docker_policy.py").read_text()
    assert '"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"' in policy
    assert "Sandbox execution user is fixed" in backend
    assert "effective_timeout_ms = min" in backend
    assert "class DockerSandboxPolicy" in policy
    assert "validate_execution" in policy
    assert "validate_resources" in policy
    assert "SANDBOX_ID_PATTERN" in policy
    assert "PROXY_NETWORK_LABEL" in policy
    assert 'attrs.get("Driver") != "bridge"' in policy
    assert 'not attrs.get("Internal", False)' in policy


def test_container_security_policy_is_shared_by_pool_and_ephemeral_paths():
    """Runtime selection must have one implementation across lifecycle paths."""
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert "DockerContainerPolicy.pool_config" in source
    assert "DockerContainerPolicy.runtime" in executor
    assert "DockerContainerPolicy.runtime" in backend
    assert "expected_runtime =" not in executor
    assert "expected_runtime =" not in backend

    class _Settings:
        SECURE_RUNTIME_TYPE = "gvisor"
        DOCKER_RUNTIME = "runsc"

    assert DockerContainerPolicy.runtime(_Settings()) == "runsc"


def test_network_enabled_ephemeral_execution_requires_policy_validation():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    network_branch = source[source.index("def _network_config"):source.index("def _resource_limits")]
    assert "DockerSandboxPolicy(self.client)" in network_branch
    assert ".attachment(True)" in network_branch
    assert ".enforce_environment" in network_branch
    assert "elif request.allow_network" not in source


def test_pooled_execution_never_retries_after_partial_failure():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    start = source.index("        except Exception as e:", source.index("async def _execute_pooled"))
    end = source.index("    def _execute_sync", start)
    block = source[start:end]
    assert "refusing automatic rerun" in block
    assert "run_in_executor(None, self._execute_sync, request)" not in block


def test_network_enabled_execution_bypasses_network_none_pool():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "and not request.allow_network" in source


def test_pool_reset_reaps_background_processes_before_reuse():
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    assert "sandbox-owned process reap" in source or "Reap every" in source
    assert "signal.SIGKILL" in source
    assert "sandbox process reap failed" in source


def test_pool_creation_enforces_secure_runtime():
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    assert "validate_secure_runtime_on_startup" in source
    assert 'config["runtime"] = runtime' in source


def test_pool_release_has_exclusive_reset_state():
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    assert 'RESETTING = "resetting"' in source
    assert "container.state = ContainerState.RESETTING" in source


def test_pool_creation_is_gated_under_concurrent_misses():
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    assert "self._create_lock = asyncio.Lock()" in source
    assert "Pool at hard capacity" in source
    assert "Another waiter may have created a container" in source


def test_wait_failures_are_not_all_reported_as_timeouts():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "def _is_wait_timeout" in source
    assert "if not _is_wait_timeout(wait_error):" in source
    assert "except Exception:\n                # Timeout" not in source
    assert "except Exception:\n                    try:\n                        await loop.run_in_executor(None, container.kill)" not in source


def test_streaming_uploads_inputs_before_starting_user_code():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    stream = source[source.index("async def execute_stream"):]
    assert "Create a stopped container" in stream
    assert stream.index("container.put_archive") < stream.index("await loop.run_in_executor(None, container.start)")


def test_streaming_preserves_channels_and_bounds_output():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    stream = source[source.index("async def execute_stream"):]
    assert "demux=True" in stream
    assert '("stdout", "stderr")' in stream
    assert "output_limit = max(0, int(request.max_output_bytes))" in stream
    assert "remaining = output_limit - output_bytes" in stream


def test_non_streaming_logs_are_read_with_a_bound():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "_read_container_logs(container, stdout=True" in source
    assert "stream=True, follow=False" in source
    assert "remaining = max(0, int(limit))" in source


def test_direct_executor_validates_dataclass_inputs_at_boundary():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "Execution timeout must be a positive integer" in source
    assert "Maximum output size must be a non-negative integer" in source
    assert "CPU allocation must be between 0.1 and 64 cores" in source
    assert "Memory allocation must be between 16 and 65536 MiB" in source


def test_executor_reuses_network_policy_for_client_lifetime():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "self._network_policy" in source
    assert "def _get_network_policy" in source
    assert "self._network_policy.client is not self.client" in source
    assert '"volumes":      volumes' not in source


def test_pooled_execution_cleans_up_on_client_cancellation():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    pooled = source[source.index("async def _execute_pooled"):source.index("    def _execute_sync", source.index("async def _execute_pooled"))]
    assert "except asyncio.CancelledError" in pooled
    assert "release(pooled.pool_id, reset=False)" in pooled
    assert "container.kill" in pooled


def test_pool_releases_require_matching_lease_capability_when_available():
    source = Path("thinkdome/sandbox/pool/manager.py").read_text()
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "lease_token: str = \"\"" in source
    assert "Rejected stale lease release" in source
    assert "lease_token=pooled.lease_token" in executor


def test_network_access_does_not_grant_privileged_port_capability():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert 'cap_add = ["NET_BIND_SERVICE"]' not in source
    assert "capability set empty for every network mode" in source


def test_container_profiles_pin_ipc_privilege_and_path_boundaries():
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert '"ipc_mode":     "private"' in executor
    assert '"privileged":   False' in executor
    assert "privileged=False" in backend
    assert '"ipc_mode": "private"' in policy
    assert "SAFE_PATH" in policy
    assert 'environment["PATH"] = DockerExecutionPolicy.SAFE_PATH' in executor


def test_workspace_and_shared_memory_profiles_are_bounded_everywhere():
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert "SANDBOX_TMPFS_SIZE_MB" in backend
    assert "SANDBOX_TMPFS_SIZE_MB" in policy
    assert "shm_size=DockerContainerPolicy.shm_size(self.settings)" in backend
    assert '"shm_size": cls.shm_size(settings)' in policy
    assert "mode=1777" in backend
    assert "mode=1777" in policy


def test_shared_memory_is_a_validated_general_setting():
    config = Path("thinkdome/core/config.py").read_text()
    assert "SHM_SIZE_MB: int = Field(default=64, ge=16, le=1024)" in config
    assert "SANDBOX_TMPFS_SIZE_MB: int = Field(default=64, ge=16, le=4096)" in config


def test_docker_sizes_are_revalidated_at_policy_boundary():
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert "def _bounded_size" in policy
    assert "SHM_SIZE_MB" in policy
    assert "SANDBOX_TMPFS_SIZE_MB" in policy


def test_environment_and_numeric_boundaries_reject_malformed_values():
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "Environment keys and values must be strings" in policy
    assert "Environment exceeds the 65536-byte execution limit" in policy
    assert "type(value) is not int" in policy
    assert "type(request.timeout_ms) is not int" in executor
    assert "type(request.max_output_bytes) is not int" in executor


def test_cold_and_streaming_execution_have_a_global_admission_limit():
    config = Path("thinkdome/core/config.py").read_text()
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "DOCKER_MAX_CONCURRENT_EXECUTIONS: int = Field(default=64, ge=1, le=4096)" in config
    assert "self._execution_slots = asyncio.Semaphore" in source
    assert "async def _execute_cold" in source
    assert "async with self._execution_slots" in source
    assert "slot_acquired = False" in source


def test_backend_exec_uses_same_environment_boundary():
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert "DockerExecutionPolicy.sanitize_environment" in backend
    assert 'execution_env["PATH"] = DockerExecutionPolicy.SAFE_PATH' in backend


def test_backend_timeout_removes_container_and_invalidates_handle():
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert "def _terminate_container" in backend
    assert "container.remove(force=True)" in backend
    assert 'handle.metadata["destroyed"] = True' in backend
    assert "Sandbox handle is no longer active" in backend


def test_command_and_code_payloads_have_explicit_size_bounds():
    policy = Path("thinkdome/sandbox/network/docker_policy.py").read_text()
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    config = Path("thinkdome/core/config.py").read_text()
    assert "len(command) > 128" in policy
    assert "65_536" in policy
    assert "MAX_EXECUTION_CODE_BYTES" in config
    assert "Execution code exceeds the" in executor


def test_backend_execution_validates_actual_container_network_state():
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert 'container.attrs.get("HostConfig")' in backend
    assert "network configuration does not match its handle" in backend
    assert "unauthorized Docker network" in backend


def test_backend_execution_validates_container_sandbox_ownership():
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    assert '"thinkdome.sandbox_id": sandbox_id' in backend
    assert 'labels.get("thinkdome.sandbox_id") != handle.sandbox_id' in backend
    assert "container ownership does not match its handle" in backend


def test_file_descriptor_budget_is_general_and_applied_everywhere():
    config = Path("thinkdome/core/config.py").read_text()
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    backend = Path("thinkdome/sandbox/executors/docker/backend.py").read_text()
    executor = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    assert "SANDBOX_NOFILE_LIMIT: int = Field(default=1024, ge=64, le=65536)" in config
    assert "def nofile_ulimit" in policy
    assert "ulimits=DockerContainerPolicy.nofile_ulimit" in backend
    assert '"ulimits":      DockerContainerPolicy.nofile_ulimit' in executor


def test_pooled_and_ephemeral_paths_share_environment_sanitizer():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    policy = Path("thinkdome/sandbox/executors/docker/container_policy.py").read_text()
    assert "class DockerExecutionPolicy" in policy
    assert "exec_env = DockerExecutionPolicy.sanitize_environment(request.env_vars)" in source
    assert "environment = DockerExecutionPolicy.sanitize_environment(request.env_vars)" in source
    assert '"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"' in policy


def test_pooled_execution_uses_shared_command_resolution():
    source = Path("thinkdome/sandbox/executors/docker/python_executor.py").read_text()
    pooled = source[source.index("async def _execute_pooled"):source.index("    def _execute_sync", source.index("async def _execute_pooled"))]
    assert "cmd = self._execution_command(request)" in pooled


def test_seccomp_profile_allows_statx_needed_by_current_runc():
    """runc uses statx while safely reopening its exec FIFO during startup."""
    profile_path = Path(__file__).resolve().parents[1] / "security" / "seccomp.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    allowed = {
        syscall
        for rule in profile["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        for syscall in rule["names"]
    }

    assert "statx" in allowed
