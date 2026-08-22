"""Tests for Sandbox Lifecycle state machine, TTL bounding by role, and background reaper process."""

import pytest
import asyncio
import time
from thinkdome.sandbox.core.lifecycle_service import SandboxLifecycleService, SandboxState
from thinkdome.sandbox.core.reaper import SandboxReaper


def test_ttl_bounding_by_role():
    svc = SandboxLifecycleService()
    
    # Free tier max 15m (900s)
    free_ttl = svc.bound_ttl_by_role(3600, role="FREE")
    assert free_ttl == 900
    
    # Agent tier max 2h (7200s)
    agent_ttl = svc.bound_ttl_by_role(10000, role="AGENT_STANDARD")
    assert agent_ttl == 7200
    
    # Admin tier max 24h (86400s)
    admin_ttl = svc.bound_ttl_by_role(20000, role="SUPER_ADMIN")
    assert admin_ttl == 20000


@pytest.mark.asyncio
async def test_lifecycle_state_machine_and_reaper():
    lifecycle_svc = SandboxLifecycleService()
    reaper = SandboxReaper(lifecycle_svc, check_interval_sec=0.1, default_idle_timeout_sec=0.2)
    
    # Register a sandbox expiring in 0.1 seconds
    sb_info = lifecycle_svc.register_sandbox(
        sandbox_id="sb_expiring_test",
        timeout_sec=0.1,
        owner="testuser",
        purpose="unit_test",
        role="FREE"
    )
    assert sb_info.state == SandboxState.RUNNING

    # Wait for TTL to pass
    await asyncio.sleep(0.25)

    # Run reaper cycle
    reaped = await reaper.reap_expired_sandboxes()
    assert reaped == 1
    assert "sb_expiring_test" not in lifecycle_svc._sandboxes


@pytest.mark.asyncio
async def test_reaper_idempotency():
    lifecycle_svc = SandboxLifecycleService()
    reaper = SandboxReaper(lifecycle_svc)
    
    # Register sandbox and destroy it manually
    lifecycle_svc.register_sandbox("sb_manual_destroy", timeout_sec=1)
    await lifecycle_svc.destroy_sandbox("sb_manual_destroy", actor="manual_test")
    
    # Second destroy attempt should be safe and idempotent
    res = await lifecycle_svc.destroy_sandbox("sb_manual_destroy", actor="retry_test")
    assert res.state == SandboxState.DESTROYED
