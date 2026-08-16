"""Outbound Network Policy definition and evaluation.

Implements per-sandbox network egress policy rules matching OpenSandbox specs:
  - defaultAction: "allow" | "deny"
  - egress rules: list of NetworkRule with action ("allow" | "deny"), target (hostname, domain wildcard, or IP), ports, and protocols.

Provides evaluation helper for outbound HTTP/HTTPS requests.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set
from pydantic import BaseModel, Field, field_validator


class NetworkRule(BaseModel):
    """Rule defining egress access for a target domain or IP."""
    action: str = Field("allow", description="Action to take: 'allow' or 'deny'")
    target: str = Field(..., description="Target hostname (e.g. 'api.github.com'), wildcard (e.g. '*.github.com'), or CIDR")
    ports: Optional[List[int]] = Field(None, description="Allowed ports, e.g. [80, 443]")
    protocols: Optional[List[str]] = Field(None, description="Allowed protocols, e.g. ['tcp', 'udp']")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("allow", "deny"):
            raise ValueError("action must be 'allow' or 'deny'")
        return v_lower


class NetworkPolicy(BaseModel):
    """Network egress policy for a sandbox container."""
    default_action: str = Field("deny", alias="defaultAction", description="Default action for unmatched egress: 'allow' or 'deny'")
    egress: List[NetworkRule] = Field(default_factory=list, description="List of egress rules evaluated in order")

    @field_validator("default_action")
    @classmethod
    def validate_default_action(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("allow", "deny"):
            raise ValueError("defaultAction must be 'allow' or 'deny'")
        return v_lower


def get_default_network_policy() -> NetworkPolicy:
    """Return default strict NetworkPolicy with defaultAction='deny' and no automatic rules.

    All outbound destinations must be explicitly permitted by writing rules into network_policy.egress.
    """
    return NetworkPolicy(
        defaultAction="deny",
        egress=[],
    )


def _match_target(target_pattern: str, domain_or_ip: str) -> bool:
    """Check if domain_or_ip matches a target pattern (supports wildcard '*.domain.com')."""
    pattern = target_pattern.strip().lower()
    target_host = domain_or_ip.strip().lower()

    if pattern == "*" or pattern == target_host:
        return True

    if pattern.startswith("*."):
        suffix = pattern[1:]  # e.g. ".github.com"
        return target_host.endswith(suffix) or target_host == pattern[2:]

    # Convert wildcard pattern into regex
    regex_pattern = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return bool(re.match(regex_pattern, target_host, re.IGNORECASE))


def evaluate_network_policy(
    policy: NetworkPolicy,
    host: str,
    port: int = 443,
    protocol: str = "tcp",
) -> tuple[bool, str]:
    """Evaluate an outbound request against a NetworkPolicy.

    Args:
        policy: NetworkPolicy instance
        host: Destination hostname or IP
        port: Destination port (default: 443)
        protocol: Transport protocol (default: 'tcp')

    Returns:
        tuple (allowed: bool, reason: str)
    """
    for rule in policy.egress:
        if _match_target(rule.target, host):
            if rule.ports and port not in rule.ports:
                continue
            if rule.protocols and protocol.lower() not in [p.lower() for p in rule.protocols]:
                continue
            allowed = (rule.action == "allow")
            reason = f"Matched egress rule target='{rule.target}' action='{rule.action}'"
            return allowed, reason

    allowed = (policy.default_action == "allow")
    reason = f"Default action '{policy.default_action}' applied for target '{host}'"
    return allowed, reason
