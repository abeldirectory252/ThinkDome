"""Tests for network audit API endpoints and Web UI backend data sources."""

import pytest
from fastapi.testclient import TestClient
from thinkdome.api.server import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        token = test_client.app.state.auth_service.create_api_key("Default test admin", token_type="ADMIN")["token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def test_network_audit_api_flow(client):
    """Test network stats, audit log, and rules endpoints."""
    proxy = client.app.state.egress_proxy

    # Add explicit rule to test allowed evaluation
    from thinkdome.sandbox.network.egress import EgressRule
    proxy.add_rule(EgressRule(domain_pattern=r"(?:.*\.)?pypi\.org$", description="Explicit PyPI rule"))

    # Evaluate requests to generate audit log entries
    proxy.evaluate("https://pypi.org/simple/pip/", method="GET", sandbox_id="sb_test_net_1")
    proxy.evaluate("https://blocked-domain.com/data", method="POST", sandbox_id="sb_test_net_1")

    # 1. Stats endpoint
    res_stats = client.get("/v1/network/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_evaluations"] >= 2
    assert stats["allowed"] >= 1
    assert stats["denied"] >= 1

    # 2. Audit log endpoint
    res_audit = client.get("/v1/network/audit-log?limit=10")
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert audit_data["count"] >= 2
    urls = [log["url"] for log in audit_data["audit_log"]]
    assert "https://pypi.org/simple/pip/" in urls

    # Filter by sandbox_id
    res_sb_audit = client.get("/v1/network/audit-log?sandbox_id=sb_test_net_1")
    assert res_sb_audit.status_code == 200
    assert len(res_sb_audit.json()["audit_log"]) >= 2

    # 3. Rules endpoint
    res_rules = client.get("/v1/network/rules")
    assert res_rules.status_code == 200
    rules_data = res_rules.json()
    assert rules_data["count"] >= 1
    patterns = [r["domain_pattern"] for r in rules_data["rules"]]
    assert any("pypi" in p for p in patterns)
