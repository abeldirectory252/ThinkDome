"""Credential Vault models for auth rules, bindings, and placeholder substitutions.

Supports 5 auth types:
  - 'bearer': injects Authorization: Bearer <credential>
  - 'basic': injects Authorization: Basic <credential>
  - 'apiKey': injects <header_name>: <credential>
  - 'customHeaders': injects list of custom headers
  - 'passthrough': no auth header injection (used with placeholder substitutions)

Supports 4 substitution surfaces:
  - 'header', 'path', 'query', 'body'
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


class CredentialSource(BaseModel):
    """Source definition for a credential."""
    value: str = Field(..., description="Secret value (write-only, redacted in responses)")


class Credential(BaseModel):
    """Credential stored in Vault."""
    name: str = Field(..., description="Unique credential identifier, e.g., 'github-token'")
    source: CredentialSource


class MatchRule(BaseModel):
    """Criteria for matching an outbound HTTPS request against a vault binding."""
    schemes: List[str] = Field(default_factory=lambda: ["https"], description="Allowed schemes, e.g., ['https']")
    hosts: List[str] = Field(..., description="Allowed destination hosts, e.g., ['api.github.com']")
    methods: Optional[List[str]] = Field(None, description="Allowed HTTP methods, e.g., ['GET', 'POST']")
    paths: Optional[List[str]] = Field(None, description="Allowed URL path globs, e.g., ['/v1/*']")


class CustomHeaderSpec(BaseModel):
    """Header name to credential name mapping."""
    name: str = Field(..., description="Header name, e.g., 'X-API-Key'")
    credential: str = Field(..., description="Credential name in vault")


class SubstitutionRule(BaseModel):
    """Scoped placeholder substitution rule."""
    credential: str = Field(..., description="Credential name in vault")
    placeholder: str = Field(..., description="Placeholder string in sandbox request, e.g. '__api_key__'")
    surfaces: List[Literal["header", "path", "query", "body"]] = Field(
        ..., alias="in", description="Surfaces to perform substitution on"
    )


class AuthRule(BaseModel):
    """Auth injection rule for a binding."""
    type: Literal["bearer", "basic", "apiKey", "customHeaders", "passthrough"]
    name: Optional[str] = Field(None, description="Header name for 'apiKey' type")
    credential: Optional[str] = Field(None, description="Credential name for 'bearer', 'basic', or 'apiKey'")
    headers: Optional[List[CustomHeaderSpec]] = Field(None, description="List of headers for 'customHeaders'")
    substitutions: Optional[List[SubstitutionRule]] = Field(None, description="Scoped placeholder substitutions")


class CredentialBinding(BaseModel):
    """Binding associating match criteria with an auth injection rule."""
    name: str = Field(..., description="Binding identifier, e.g. 'github-api'")
    match: MatchRule
    auth: AuthRule


def match_path_glob(pattern: str, path: str) -> bool:
    """Match a URL path against a glob pattern (e.g. '/v1/*')."""
    p = pattern.strip()
    if p == "*" or p == path:
        return True
    regex_pattern = "^" + re.escape(p).replace(r"\*", ".*") + "$"
    return bool(re.match(regex_pattern, path))


def evaluate_binding_match(
    binding: CredentialBinding,
    scheme: str,
    host: str,
    method: str,
    path: str,
) -> bool:
    """Evaluate whether an outbound request matches a CredentialBinding."""
    m = binding.match

    # Scheme
    if m.schemes and scheme.lower() not in [s.lower() for s in m.schemes]:
        return False

    # Host (support exact and wildcard matching)
    host_lower = host.lower()
    matched_host = False
    for h in m.hosts:
        h_lower = h.lower()
        if h_lower == "*" or h_lower == host_lower:
            matched_host = True
            break
        if h_lower.startswith("*.") and (host_lower.endswith(h_lower[1:]) or host_lower == h_lower[2:]):
            matched_host = True
            break
    if not matched_host:
        return False

    # Method
    if m.methods and method.upper() not in [meth.upper() for meth in m.methods]:
        return False

    # Path
    if m.paths:
        matched_path = any(match_path_glob(p, path) for p in m.paths)
        if not matched_path:
            return False

    return True
