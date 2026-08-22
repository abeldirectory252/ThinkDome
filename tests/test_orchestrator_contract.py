from datetime import datetime, timedelta, timezone

from thinkdome.control_plane.orchestrator import (
    OrchestratorAuthorization,
    OrchestratorOperation,
    OrchestratorSandboxRequest,
)


def test_orchestrator_authorization_is_operation_scoped_and_expirable():
    auth = OrchestratorAuthorization(
        organization_id="org",
        project_id="project",
        sandbox_id="sandbox",
        operation=OrchestratorOperation.CREATE,
        request_id="req-1",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    request = OrchestratorSandboxRequest(
        authorization=auth,
        image_ref="registry.example/runner@sha256:abc",
        cpu_millis=500,
        memory_bytes=512 * 1024 * 1024,
        pids=64,
    )
    assert request.authorization.operation == OrchestratorOperation.CREATE
    assert not request.authorization.is_expired()
