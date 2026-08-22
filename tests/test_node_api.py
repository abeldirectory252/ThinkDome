from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
import httpx
import pytest

from thinkdome.control_plane.auth import NodeAuthorizationSigner
from thinkdome.control_plane.node_agent import NodeAgent
from thinkdome.control_plane.node_api import AUTH_HEADER, create_node_router
from thinkdome.control_plane.orchestrator import (
    OrchestratorAuthorization,
    OrchestratorOperation,
    OrchestratorResult,
)


class FakeOrchestrator:
    async def create_sandbox(self, request):
        return None

    async def execute(self, request):
        return OrchestratorResult(request_id=request.authorization.request_id, exit_code=0, stdout="ok")

    async def pause_sandbox(self, authorization):
        return None

    async def resume_sandbox(self, authorization):
        return None

    async def terminate_sandbox(self, authorization):
        return None


def _auth():
    return OrchestratorAuthorization(
        organization_id="org",
        project_id="project",
        sandbox_id="sandbox",
        operation=OrchestratorOperation.EXECUTE,
        request_id="request-1",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )


@pytest.mark.asyncio
async def test_node_api_requires_token_and_dispatches_verified_request():
    signer = NodeAuthorizationSigner(b"a" * 32)
    app = FastAPI()
    app.include_router(create_node_router(NodeAgent(signer, FakeOrchestrator())))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node")
    auth = _auth()
    payload = {"authorization": auth.model_dump(mode="json"), "code": "print('ok')"}

    missing = await client.post("/internal/node/sandboxes/execute", json=payload)
    assert missing.status_code == 401

    response = await client.post(
        "/internal/node/sandboxes/execute",
        json=payload,
        headers={AUTH_HEADER: signer.issue(auth)},
    )
    assert response.status_code == 200
    assert response.json()["stdout"] == "ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_node_api_rejects_wrong_operation_token():
    signer = NodeAuthorizationSigner(b"a" * 32)
    app = FastAPI()
    app.include_router(create_node_router(NodeAgent(signer, FakeOrchestrator())))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node")
    auth = _auth()
    wrong = auth.model_copy(update={"operation": OrchestratorOperation.PAUSE})
    payload = {"authorization": auth.model_dump(mode="json"), "code": "print('no')"}

    response = await client.post(
        "/internal/node/sandboxes/execute",
        json=payload,
        headers={AUTH_HEADER: signer.issue(wrong)},
    )
    assert response.status_code == 403
    await client.aclose()
