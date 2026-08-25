"""Live Docker Isolation Test Campaign.

Forces EXECUTOR_BACKEND="docker" and executes live code inside the isolated Docker container
to empirically verify host reachability, process isolation, filesystem isolation, and network bounds.
"""

import os
import socket
import pytest
import threading
from thinkdome.core.config import Settings
from thinkdome.sandbox.executors.docker.python_executor import PythonDockerExecutor
from thinkdome.sandbox.executors.base import ExecRequest


@pytest.fixture
async def docker_executor():
    """Initialize PythonDockerExecutor directly."""
    settings = Settings(
        EXECUTOR_BACKEND="docker",
        EXECUTOR_IMAGE="thinkdome-executor:latest",
        EXECUTOR_BACKEND_USE_FALLBACK=False,
    )
    executor = PythonDockerExecutor(settings)
    await executor.initialize()
    return executor


@pytest.mark.asyncio
async def test_docker_python_socket_host_reachability(docker_executor):
    """Test pure Python socket connectivity to host IP from inside untrusted LLM Docker container (network_mode=none)."""
    # Start temporary socket listener on host
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    host_port = sock.getsockname()[1]

    def accept_one():
        try:
            sock.settimeout(2.0)
            conn, _ = sock.accept()
            conn.close()
        except Exception:
            pass
        finally:
            sock.close()

    threading.Thread(target=accept_one, daemon=True).start()

    code = f"""
import socket
results = {{}}
# Attempt to reach host IP on host port {host_port}
host_ips = ["127.0.0.1", "172.17.0.1", "10.0.0.1", "1.1.1.1"]
for ip in host_ips:
    try:
        s = socket.create_connection((ip, {host_port}), timeout=1.0)
        s.close()
        results[ip] = "CONNECTED"
    except Exception as e:
        results[ip] = f"FAILED: {{e}}"
print("SOCKET_PROBE_RESULTS:", results)
"""
    req = ExecRequest(
        code=code,
        language="python",
        caller_role="LLM",
        allow_network=False,
        timeout_ms=10000,
    )
    res = await docker_executor.execute(req)
    print("\n--- DOCKER CONTAINER NETWORK PROBE OUTPUT ---")
    print("STDOUT:", res.stdout)

    # In network_mode="none", ALL outbound connections (including 172.17.0.1 host IP and external IPs) MUST fail
    assert res.exit_code == 0
    assert "'172.17.0.1': 'FAILED: [Errno 101] Network is unreachable'" in res.stdout or "Network is unreachable" in res.stdout
    assert "'1.1.1.1': 'FAILED: [Errno 101] Network is unreachable'" in res.stdout or "Network is unreachable" in res.stdout
    assert "'CONNECTED'" not in res.stdout


@pytest.mark.asyncio
async def test_docker_container_non_root_shadow_permission(docker_executor):
    """Test that non-root user (UID 1000:1000) inside container cannot read /etc/shadow."""
    code = """
import os
try:
    with open("/etc/shadow", "r") as f:
        data = f.read()
    print("SHADOW_READ_SUCCESS")
except Exception as e:
    print(f"SHADOW_READ_DENIED: {e}")
"""
    req = ExecRequest(
        code=code,
        language="python",
        caller_role="LLM",
        timeout_ms=10000,
    )
    res = await docker_executor.execute(req)
    print("STDOUT:", res.stdout)
    assert "SHADOW_READ_DENIED: [Errno 13] Permission denied: '/etc/shadow'" in res.stdout


@pytest.mark.asyncio
async def test_docker_host_filesystem_unreachable(docker_executor):
    """Test reading host files (/home/sandbox/.env, /var/run/docker.sock) from inside Docker container."""
    code = """
import os
files = ["/home/sandbox/.env", "/var/run/docker.sock", "/root/.bashrc"]
found = []
for f in files:
    if os.path.exists(f):
        found.append(f)
print("FOUND_HOST_FILES:", found)
"""
    req = ExecRequest(
        code=code,
        language="python",
        caller_role="LLM",
        timeout_ms=10000,
    )
    res = await docker_executor.execute(req)
    print("STDOUT:", res.stdout)
    assert res.stdout.strip() == "FOUND_HOST_FILES: []"


@pytest.mark.asyncio
async def test_docker_host_processes_invisible(docker_executor):
    """Test that host PID 1 (systemd/init) and host processes are invisible inside container PID namespace."""
    code = """
import os
try:
    cmdline = open("/proc/1/cmdline", "r").read()
    print("PID1_CMDLINE:", cmdline)
except Exception as e:
    print("PID1_ERR:", e)
"""
    req = ExecRequest(
        code=code,
        language="python",
        caller_role="LLM",
        timeout_ms=10000,
    )
    res = await docker_executor.execute(req)
    print("STDOUT:", res.stdout)
    # PID 1 inside container is the Python/bash entrypoint, NOT host systemd/init
    assert "systemd" not in res.stdout
    assert "init" not in res.stdout
