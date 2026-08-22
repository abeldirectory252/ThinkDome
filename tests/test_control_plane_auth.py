from datetime import datetime, timedelta, timezone

import pytest

from thinkdome.control_plane.auth import InvalidNodeAuthorization, NodeAuthorizationSigner
from thinkdome.control_plane.orchestrator import OrchestratorAuthorization, OrchestratorOperation


def _authorization(expires=None):
    return OrchestratorAuthorization(
        organization_id="org",
        project_id="project",
        sandbox_id="sandbox",
        operation=OrchestratorOperation.EXECUTE,
        request_id="request-1",
        expires_at=expires or datetime.now(timezone.utc) + timedelta(seconds=30),
    )


def test_node_authorization_round_trips_and_binds_operation():
    signer = NodeAuthorizationSigner(b"a" * 32)
    token = signer.issue(_authorization())
    verified = signer.verify(token)
    assert verified.sandbox_id == "sandbox"
    assert verified.operation == OrchestratorOperation.EXECUTE


def test_node_authorization_rejects_tampering_and_expiry():
    signer = NodeAuthorizationSigner(b"a" * 32)
    token = signer.issue(_authorization())
    parts = token.split(".")
    parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    with pytest.raises(InvalidNodeAuthorization):
        signer.verify(".".join(parts))

    expired = signer.issue(_authorization(datetime.now(timezone.utc) - timedelta(seconds=1)))
    with pytest.raises(InvalidNodeAuthorization):
        signer.verify(expired)
