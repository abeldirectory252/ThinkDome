"""Regression checks for high-impact management API authentication."""

from thinkdome.sandbox.executors.microvm.api import router as microvm_router
from thinkdome.sandbox.snapshots.api import router as snapshots_router
from thinkdome.api.routes.execution.diagnostics import router as diagnostics_router
from thinkdome.api.routes.execution.lifecycle import router as lifecycle_router
from thinkdome.api.routes.execution.metadata import router as metadata_router
from thinkdome.api.routes.execution.network_audit import router as network_audit_router
from thinkdome.security.api.vault import router as vault_router
from thinkdome.platform.observability.api.observability import router as observability_router
from thinkdome.core.api.router import router as dynamic_api_router
from thinkdome.security.api.users import router as users_router
from thinkdome.security.api.roles import router as roles_router
from thinkdome.security.api.permissions import router as permissions_router
from thinkdome.security.api.audit import router as audit_router
from pathlib import Path


def test_microvm_and_snapshot_routers_require_authentication():
    for router in (microvm_router, snapshots_router, diagnostics_router, lifecycle_router,
                   metadata_router, network_audit_router, vault_router):
        assert router.dependencies


def test_observability_and_dynamic_metadata_routers_require_authentication():
    assert observability_router.dependencies
    assert dynamic_api_router.dependencies
    for router in (users_router, roles_router, permissions_router, audit_router):
        assert router.dependencies


def test_mcp_sse_uses_authenticated_identity():
    source = Path("thinkdome/api/server.py").read_text()
    assert "async def handle_sse(request: Request, user: dict = Depends(get_current_user))" in source
    assert 'request.headers.get("X-User-Role"' not in source


def test_core_websocket_rejects_missing_authentication():
    source = Path("thinkdome/core/api/server.py").read_text()
    assert 'if not token or not auth_svc or not auth_svc.verify_token(token):' in source
    assert "async def handle_sse(request: Request, user: dict = Depends(get_current_user))" in source


def test_monitor_websocket_does_not_use_query_tokens():
    source = Path("thinkdome/platform/observability/api/monitor.py").read_text()
    assert "websocket.query_params.get(\"token\")" not in source
    assert "websocket.cookies.get(\"session_token\")" in source
