import asyncio

import pytest
from fastapi import HTTPException

from thinkdome.api.routes.control_plane import PlacementRequest, create_placement


class _Lifecycle:
    class _Repository:
        def get_ready_heartbeats(self):
            return []

    repository = _Repository()


def test_placement_requires_authenticated_tenant_context():
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            create_placement(
                PlacementRequest(project_id="p", sandbox_id="s"),
                organization_id="org-header",
                idempotency_key="key",
                current_user={"role": "AGENT_STANDARD"},
                lifecycle=_Lifecycle(),
            )
        )
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "TENANT::CONTEXT_REQUIRED"
