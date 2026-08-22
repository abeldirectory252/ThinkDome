from datetime import datetime, timezone

import pytest

from thinkdome.control_plane.microvm_adapter import MicroVMNodeAdapter
from thinkdome.control_plane.orchestrator import (
    OrchestratorAuthorization,
    OrchestratorExecutionRequest,
    OrchestratorOperation,
)


class FakeExecutor:
    async def execute(self, request):
        from thinkdome.sandbox.executors.base import ExecResult
        return ExecResult(stdout="ok", exit_code=0)


def auth():
    return OrchestratorAuthorization(
        organization_id="org", project_id="project", sandbox_id="sandbox",
        operation=OrchestratorOperation.EXECUTE, request_id="req",
        expires_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_microvm_adapter_rejects_execution_before_provisioning():
    adapter = MicroVMNodeAdapter(FakeExecutor())
    request = OrchestratorExecutionRequest(authorization=auth(), code="print('x')")
    with pytest.raises(RuntimeError, match="not provisioned"):
        await adapter.execute(request)
