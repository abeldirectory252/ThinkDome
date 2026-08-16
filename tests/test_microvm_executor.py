"""Tests for MicroVM Execution Backend and Initramfs OverlayFS setup."""

import pytest
from thinkdome.sandbox.executors.microvm.executor import MicroVMExecutor
from thinkdome.sandbox.executors.base import ExecRequest
from thinkdome.core.config import Settings


import os

@pytest.mark.asyncio
async def test_microvm_executor_init_and_spawn():
    """Test MicroVM executor initialization and instance spawning."""
    if not os.path.exists("/dev/kvm") or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        pytest.skip("KVM hardware acceleration (/dev/kvm) not available in environment")
    settings = Settings()
    executor = MicroVMExecutor(settings)
    await executor.initialize()

    # Verify initialization
    assert await executor.health_check()

    # Test spawning MicroVM instance
    inst = executor.spawn_vm(name="test-mvm", memory_mb=256, vcpus=1)
    assert inst.name == "test-mvm"
    assert inst.status == "RUNNING"
    assert inst.vm_id in executor.instances
    assert inst.ip_address.startswith("10.20.1.")

    # Shutdown
    await executor.shutdown()
    assert len(executor.instances) == 0


@pytest.mark.asyncio
async def test_microvm_execution():
    """Test executing code inside MicroVM isolated environment."""
    if not os.path.exists("/dev/kvm") or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        pytest.skip("KVM hardware acceleration (/dev/kvm) not available in environment")
    settings = Settings()
    settings.EXECUTOR_BACKEND_USE_FALLBACK = True
    executor = MicroVMExecutor(settings)
    await executor.initialize()


    req = ExecRequest(
        code="print('Hello from isolated MicroVM')",
        language="python",
        timeout_ms=5000,
    )
    result = await executor.execute(req)
    assert result.exit_code == 0
    assert "Hello from isolated MicroVM" in result.stdout
    assert not result.timed_out
