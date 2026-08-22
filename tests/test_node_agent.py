from datetime import datetime, timedelta, timezone

import pytest

from thinkdome.control_plane.auth import NodeAuthorizationSigner
from thinkdome.control_plane.node_agent import NodeAgent, NodeAgentRequestError
from thinkdome.control_plane.orchestrator import (
    OrchestratorAuthorization,
    OrchestratorExecutionRequest,
    OrchestratorOperation,
    OrchestratorResult,
)


class FakeOrchestrator:
    def __init__(self):
        self.executions = 0

    async def create_sandbox(self, request):
        pass

    async def execute(self, request):
        self.executions += 1
        return OrchestratorResult(request_id=request.authorization.request_id, exit_code=0, stdout="ok")

    async def pause_sandbox(self, authorization):
        pass

    async def resume_sandbox(self, authorization):
        pass

    async def terminate_sandbox(self, authorization):
        pass


def authorization(operation=OrchestratorOperation.EXECUTE):
    return OrchestratorAuthorization(
        organization_id="org",
        project_id="project",
        sandbox_id="sandbox",
        operation=operation,
        request_id="request-1",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_node_agent_dispatches_only_matching_signed_operation():
    signer = NodeAuthorizationSigner(b"a" * 32)
    orchestrator = FakeOrchestrator()
    agent = NodeAgent(signer, orchestrator)
    auth = authorization()
    request = OrchestratorExecutionRequest(authorization=auth, code="print('ok')")

    result = await agent.execute(signer.issue(auth), request)

    assert result.stdout == "ok"
    assert orchestrator.executions == 1


@pytest.mark.asyncio
async def test_node_agent_rejects_operation_mismatch_before_dispatch():
    signer = NodeAuthorizationSigner(b"a" * 32)
    orchestrator = FakeOrchestrator()
    agent = NodeAgent(signer, orchestrator)
    auth = authorization(OrchestratorOperation.PAUSE)
    request = OrchestratorExecutionRequest(authorization=auth, code="print('no')")

    with pytest.raises(NodeAgentRequestError):
        await agent.execute(signer.issue(auth), request)
    assert orchestrator.executions == 0
