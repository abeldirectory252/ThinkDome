"""Integration and unit tests for Harness, Compute, Egress Proxy, Scheduler, and Bubblewrap."""

import pytest
import asyncio
import time
from unittest.mock import MagicMock

from thinkdome.models.manifest import SandboxManifest, GitRepositoryImport, MountSpec, CredentialExclusions
from thinkdome.harness.harness import Harness, AuditRecord
from thinkdome.services.egress_proxy import EgressProxy, EgressRule, EgressDecision
from thinkdome.services.scheduler import Scheduler, ScheduledTask
from thinkdome.executors.bubblewrap import BubblewrapExecutor, ExecRequest, ExecResult
from thinkdome.services.credential_vault import SandboxCredentials
from thinkdome.core.config import Settings


# ── 1. Sandbox Manifest tests ──────────────────────────────────────────────────

def test_manifest_validation():
    manifest_data = {
        "files": {"main.py": "print('hello')"},
        "git_repositories": [
            {"url": "https://github.com/test/repo.git", "branch": "main", "destination": "src/"}
        ],
        "mounts": [
            {"host_path": "/var/data", "container_path": "/data", "mode": "ro", "type": "bind"}
        ],
        "env_vars": {"ENV": "production"},
        "credentials": {
            "blocked_paths": ["/etc/shadow", "/root/.aws"],
            "blocked_env_vars": ["AWS_SECRET_ACCESS_KEY"]
        }
    }

    manifest = SandboxManifest.model_validate(manifest_data)
    assert manifest.files["main.py"] == "print('hello')"
    assert len(manifest.git_repositories) == 1
    assert manifest.git_repositories[0].url == "https://github.com/test/repo.git"
    assert manifest.mounts[0].mode == "ro"
    assert "AWS_SECRET_ACCESS_KEY" in manifest.credentials.blocked_env_vars


# ── 2. Harness control plane tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_harness_audit_and_approval():
    db_mock = MagicMock()
    settings = Settings()
    harness = Harness(settings, db_mock)

    # Register approval rule for sensitive tools
    harness.approvals.register_approval_rule("shell_exec", lambda caller, inp: True)

    caller_identity = {"username": "agent_bob", "role": "LLM"}

    # Mock tool executor
    async def mock_exec(name, inp):
        return {"type": "tool_result", "content": "success", "is_error": False}

    # Step 1: Execute a sensitive tool which requires approval
    res = await harness.execute_agent_step("shell_exec", {"cmd": "rm -rf /"}, caller_identity, mock_exec)
    assert res["type"] == "approval_required"
    req_id = res["approval_req_id"]

    # Step 2: Approve the request
    assert harness.approvals.approve(req_id, "admin_user") is True

    # Step 3: Verify audit log was recorded
    audit_trail = harness.get_audit_trail()
    actions = [a["action"] for a in audit_trail]
    assert "approval_requested" in actions


# ── 3. Egress Proxy tests ──────────────────────────────────────────────────────

def test_egress_proxy_rules_and_stripping():
    proxy = EgressProxy()
    proxy.add_rule(EgressRule(
        domain_pattern=r".*\.github\.com$",
        inject_headers={"Authorization": "Bearer internal_secret_token"},
        description="GitHub Rule"
    ))

    # Test allowed domain with custom header injection and client credential stripping
    headers = {
        "User-Agent": "ThinkDome",
        "Authorization": "Bearer sandbox_hijacked_token",
        "X-API-Key": "leaked_key"
    }
    decision = proxy.evaluate("https://api.github.com/user", method="GET", headers=headers)

    assert decision.allowed is True
    assert decision.matched_rule == r".*\.github\.com$"
    # Verify client credentials were removed
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers
    # Verify proxy injected the secure token
    assert decision.injected_headers["Authorization"] == "Bearer internal_secret_token"

    # Test denied domain
    decision_denied = proxy.evaluate("https://malicious.com/payload", method="POST")
    assert decision_denied.allowed is False


# ── 4. Partition Scheduler tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduler_srsf_scheduling():
    # Initialize partition scheduler
    sched = Scheduler(partition_count=2, max_concurrency_per_partition=10)

    # Track executed payloads
    run_log = []

    async def mock_worker_exec(payload):
        run_log.append(payload)
        await asyncio.sleep(0.02)

    await sched.start(executor_fn=mock_worker_exec)

    # Submit tasks with different slack/deadlines
    # Lower deadline should execute first within a partition (SRSF order)
    task1 = await sched.submit(task_id="t1", payload="task1_slow", deadline_ms=5000)
    task2 = await sched.submit(task_id="t2", payload="task2_fast", deadline_ms=50)

    # Wait for completion
    await asyncio.sleep(0.1)

    assert task2.status in ("completed", "timed_out")
    status = sched.get_status()
    assert status["total_submitted"] == 2

    await sched.stop()


# ── 5. Bubblewrap Compatibility & Exclusions tests ────────────────────────────

@pytest.mark.asyncio
async def test_bubblewrap_and_credential_protection():
    settings = Settings()
    executor = BubblewrapExecutor(settings)
    await executor.initialize()

    # Verify credentials helper matches blocked paths
    cred_exclusions = SandboxCredentials(
        blocked_paths=["/etc/passwd", "/root/.ssh"],
        blocked_env_vars=["DATABASE_URL", "JWT_SECRET"]
    )

    assert cred_exclusions.is_path_blocked("/etc/passwd") is True
    assert cred_exclusions.is_path_blocked("/etc/passwd/subdir") is True
    assert cred_exclusions.is_path_blocked("/var/tmp") is False

    env = {"USER": "sandbox", "DATABASE_URL": "postgresql://...", "JWT_SECRET": "xyz"}
    clean_env = cred_exclusions.clean_env(env)
    assert "USER" in clean_env
    assert "DATABASE_URL" not in clean_env
    assert "JWT_SECRET" not in clean_env

    # Run quick execution code request using bubblewrap (running in compatibility/subprocess fallback)
    request = ExecRequest(
        code="print('Hello Sandbox')",
        language="python",
        security_profile="HIGH_SECURITY",
        timeout_ms=3000
    )

    res = await executor.execute(request)
    assert res.exit_code == 0
    assert "Hello Sandbox" in res.stdout
