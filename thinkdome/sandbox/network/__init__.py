"""Unified Network Management Domain — Ingress Gateway, Egress Proxy, Network Policy, and Route Tokens.

This package unifies all networking and traffic management capabilities for ThinkDome sandboxes:
  - ingress: Unified Ingress Gateway (Header, URI, Wildcard strategies)
  - proxy  : Egress Proxy & domain allowlisting
  - policy : Outbound Network Policy specification
  - signing: OSEP-0011 Cryptographic Signed Route Tokens
"""

from thinkdome.sandbox.network.ingress import (
    IngressGateway,
    RoutingStrategy,
    IngressRoute,
)
from thinkdome.sandbox.network.policy import (
    NetworkPolicy,
    NetworkRule,
    evaluate_network_policy,
    get_default_network_policy,
)
from thinkdome.sandbox.network.signing import (
    build_signed_route,
    verify_signed_route,
)
from thinkdome.sandbox.network.egress import (
    EgressProxy,
    EgressRule,
    EgressDecision,
)

__all__ = [
    # Ingress Gateway
    "IngressGateway",
    "RoutingStrategy",
    "IngressRoute",
    # Network Policy
    "NetworkPolicy",
    "NetworkRule",
    "evaluate_network_policy",
    "get_default_network_policy",
    # Signed Route Tokens
    "build_signed_route",
    "verify_signed_route",
    # Egress Proxy
    "EgressProxy",
    "EgressRule",
    "EgressDecision",
]
