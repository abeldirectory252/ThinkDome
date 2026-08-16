"""Tests for default strict egress policies requiring explicit rule definition."""

import pytest
from thinkdome import Sandbox
from thinkdome.sandbox.network.policy import NetworkPolicy, NetworkRule, evaluate_network_policy
from thinkdome.sandbox.network.egress import EgressRule


def test_every_sandbox_has_ingress_and_egress():
    """Verify that every Sandbox instance comes equipped with Ingress Gateway and Egress Controls."""
    sb = Sandbox()
    assert sb.ingress_gateway is not None
    assert sb.egress_proxy is not None
    assert sb.network_policy is not None


def test_strict_default_deny_policy():
    """Verify that all unwritten domains are blocked by default until explicitly allowed via rules."""
    sb = Sandbox()

    # Unwritten domains are blocked by default
    d1 = sb.egress_proxy.evaluate("https://pypi.org/simple/requests/", method="GET")
    assert d1.allowed is False

    d2 = sb.egress_proxy.evaluate("https://api.github.com", method="GET")
    assert d2.allowed is False

    # Explicitly writing rule allows domain
    sb.egress_proxy.add_rule(EgressRule(domain_pattern=r"(?:.*\.)?pypi\.org$", description="Explicit PyPI rule"))
    d3 = sb.egress_proxy.evaluate("https://pypi.org/simple/requests/", method="GET")
    assert d3.allowed is True


def test_explicit_network_policy_rules():
    """Verify explicit NetworkPolicy rules allow specified targets while blocking unlisted ones."""
    policy = NetworkPolicy(
        defaultAction="deny",
        egress=[
            NetworkRule(action="allow", target="pypi.org", ports=[443]),
            NetworkRule(action="allow", target="*.pythonhosted.org", ports=[443]),
        ],
    )

    sb = Sandbox(network_policy=policy)

    allowed_pypi, _ = evaluate_network_policy(sb.network_policy, "pypi.org", port=443)
    assert allowed_pypi is True

    allowed_hosted, _ = evaluate_network_policy(sb.network_policy, "files.pythonhosted.org", port=443)
    assert allowed_hosted is True

    blocked_unlisted, _ = evaluate_network_policy(sb.network_policy, "untrusted.org", port=443)
    assert blocked_unlisted is False
