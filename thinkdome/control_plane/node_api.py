"""Internal node-agent HTTP transport.

Deployment must expose these routes only on a private node/control-plane
network protected by mTLS. Authorization is still verified per operation by
``NodeAgent`` so transport authentication is not the sandbox authorization.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from thinkdome.control_plane.node_agent import NodeAgent, NodeAgentRequestError
from thinkdome.control_plane.orchestrator import (
    OrchestratorAuthorization,
    OrchestratorExecutionRequest,
    OrchestratorSandboxRequest,
)

AUTH_HEADER = "X-ThinkDome-Node-Authorization"


def create_node_router(agent: NodeAgent) -> APIRouter:
    """Create the private node-agent router for one local orchestrator."""
    router = APIRouter(prefix="/internal/node", tags=["node-agent"])

    def token_or_unauthorized(token: str | None) -> str:
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "NODE::AUTH_REQUIRED", "message": f"{AUTH_HEADER} is required"},
            )
        return token

    @router.post("/sandboxes")
    async def create_sandbox(
        request: OrchestratorSandboxRequest,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        try:
            await agent.create_sandbox(token_or_unauthorized(authorization), request)
            return {"status": "accepted", "sandbox_id": request.authorization.sandbox_id}
        except NodeAgentRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "NODE::AUTHORIZATION_DENIED", "message": str(exc)},
            ) from exc

    @router.post("/sandboxes/execute")
    async def execute(
        request: OrchestratorExecutionRequest,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        try:
            result = await agent.execute(token_or_unauthorized(authorization), request)
            return result.model_dump()
        except NodeAgentRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "NODE::AUTHORIZATION_DENIED", "message": str(exc)},
            ) from exc

    async def lifecycle(
        operation: str,
        request: OrchestratorAuthorization,
        authorization: str | None,
    ):
        token = token_or_unauthorized(authorization)
        try:
            if operation == "pause":
                await agent.pause_sandbox(token, request)
            elif operation == "resume":
                await agent.resume_sandbox(token, request)
            else:
                await agent.terminate_sandbox(token, request)
            return {"status": "accepted", "sandbox_id": request.sandbox_id}
        except NodeAgentRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "NODE::AUTHORIZATION_DENIED", "message": str(exc)},
            ) from exc

    @router.post("/sandboxes/pause")
    async def pause(
        request: OrchestratorAuthorization,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        return await lifecycle("pause", request, authorization)

    @router.post("/sandboxes/resume")
    async def resume(
        request: OrchestratorAuthorization,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        return await lifecycle("resume", request, authorization)

    @router.post("/sandboxes/terminate")
    async def terminate(
        request: OrchestratorAuthorization,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        return await lifecycle("terminate", request, authorization)

    return router
