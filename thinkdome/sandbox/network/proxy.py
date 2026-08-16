"""Proxy alias module re-exporting from thinkdome.sandbox.network.egress."""

from thinkdome.sandbox.network.egress import (
    EgressRule,
    EgressDecision,
    EgressProxy,
    CREDENTIAL_HEADERS,
    CREDENTIAL_PARAMS,
)

__all__ = [
    "EgressRule",
    "EgressDecision",
    "EgressProxy",
    "CREDENTIAL_HEADERS",
    "CREDENTIAL_PARAMS",
]
