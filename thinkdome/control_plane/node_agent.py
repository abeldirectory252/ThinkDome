"""Node-agent request validation and dispatch.

The agent is intentionally transport-independent. HTTP/gRPC adapters should
call this service after authenticating the node connection (mTLS) and pass the
signed operation token in the request.
"""

from __future__ import annotations

from dataclasses import dataclass

from thinkdome.control_plane.auth import NodeAuthorizationSigner
from thinkdome.control_plane.orchestrator import (
    NodeOrchestrator,
    OrchestratorAuthorization,
    OrchestratorExecutionRequest,
    OrchestratorOperation,
    OrchestratorResult,
    OrchestratorSandboxRequest,
)


class NodeAgentRequestError(ValueError):
    """A node request failed authorization or operation validation."""


@dataclass
class NodeAgent:
    """Validates control-plane requests before invoking a local orchestrator."""

    signer: NodeAuthorizationSigner
    orchestrator: NodeOrchestrator

    def authorize(self, token: str, operation: OrchestratorOperation) -> OrchestratorAuthorization:
        authorization = self.signer.verify(token)
        if authorization.operation != operation:
            raise NodeAgentRequestError(
                f"authorization operation '{authorization.operation.value}' "
                f"does not permit '{operation.value}'"
            )
        return authorization

    async def create_sandbox(self, token: str, request: OrchestratorSandboxRequest) -> None:
        authorization = self.authorize(token, OrchestratorOperation.CREATE)
        if request.authorization != authorization:
            raise NodeAgentRequestError("request authorization does not match signed token")
        await self.orchestrator.create_sandbox(request)

    async def execute(self, token: str, request: OrchestratorExecutionRequest) -> OrchestratorResult:
        authorization = self.authorize(token, OrchestratorOperation.EXECUTE)
        if request.authorization != authorization:
            raise NodeAgentRequestError("request authorization does not match signed token")
        return await self.orchestrator.execute(request)

    async def pause_sandbox(self, token: str, authorization: OrchestratorAuthorization) -> None:
        verified = self.authorize(token, OrchestratorOperation.PAUSE)
        if authorization != verified:
            raise NodeAgentRequestError("request authorization does not match signed token")
        await self.orchestrator.pause_sandbox(authorization)

    async def resume_sandbox(self, token: str, authorization: OrchestratorAuthorization) -> None:
        verified = self.authorize(token, OrchestratorOperation.RESUME)
        if authorization != verified:
            raise NodeAgentRequestError("request authorization does not match signed token")
        await self.orchestrator.resume_sandbox(authorization)

    async def terminate_sandbox(self, token: str, authorization: OrchestratorAuthorization) -> None:
        verified = self.authorize(token, OrchestratorOperation.TERMINATE)
        if authorization != verified:
            raise NodeAgentRequestError("request authorization does not match signed token")
        await self.orchestrator.terminate_sandbox(authorization)
