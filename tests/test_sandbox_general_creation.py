"""Test general Sandbox creation matching OpenSandbox API conventions."""

import pytest
from datetime import timedelta
from thinkdome import Sandbox
from thinkdome.sandbox import SandboxImageSpec, CredentialProxyConfig
from thinkdome.sandbox.network.policy import NetworkPolicy, NetworkRule


def test_sandbox_create_general_case():
    """Verify Sandbox.create(...) accepts image, timedelta timeout, network_policy, credential_proxy, and env."""
    sandbox = Sandbox.create(
        image=SandboxImageSpec(uri="opensandbox/code-interpreter:latest"),
        timeout=timedelta(minutes=15),
        env={"CUSTOM_ENV_KEY": "custom_val_123"},
        network_policy=NetworkPolicy(
            defaultAction="deny",
            egress=[
                NetworkRule(action="allow", target="api.anthropic.com"),
                NetworkRule(action="allow", target="pypi.org"),
            ],
        ),
        credential_proxy=CredentialProxyConfig(enabled=True),
    )

    try:
        assert sandbox.image == "opensandbox/code-interpreter:latest"
        assert sandbox.timeout == 900  # 15 minutes = 900 seconds
        assert sandbox.env.get("CUSTOM_ENV_KEY") == "custom_val_123"
        assert sandbox.credential_proxy_enabled is True
        assert sandbox.network_allowed is True

        # Check egress proxy has rules from policy
        decision = sandbox.egress_proxy.evaluate("https://api.anthropic.com/v1/messages")
        assert decision.allowed is True
    finally:
        sandbox._teardown()
