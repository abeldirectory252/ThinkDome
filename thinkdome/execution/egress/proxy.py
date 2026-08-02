"""Custom egress proxy — domain allowlisting and credential stripping (Anthropic pattern).

All outbound network traffic from sandboxes is routed through this proxy layer.
The proxy enforces:
  1. Domain allowlist: only whitelisted domains can be reached
  2. Credential stripping: Authorization headers, API keys, and tokens are removed
     before forwarding requests from sandbox code
  3. Credential injection: the proxy adds the correct credentials server-side
     so secrets never enter the sandbox
"""

from __future__ import annotations

import re
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class EgressRule:
    """A single egress allowlist rule."""
    domain_pattern: str              # Regex pattern (e.g. r".*\.github\.com$")
    methods: Set[str] = field(default_factory=lambda: {"GET", "POST", "PUT", "DELETE", "PATCH"})
    inject_headers: Dict[str, str] = field(default_factory=dict)  # Server-side credential injection
    max_requests_per_min: int = 60
    description: str = ""


@dataclass
class EgressDecision:
    """Result of evaluating an egress request against the allowlist."""
    allowed: bool
    matched_rule: Optional[str] = None
    reason: str = ""
    injected_headers: Dict[str, str] = field(default_factory=dict)


# Headers that MUST be stripped from sandbox-originated requests
CREDENTIAL_HEADERS = {
    "authorization",
    "x-api-key",
    "x-auth-token",
    "x-session-token",
    "cookie",
    "proxy-authorization",
    "x-amz-security-token",
    "x-goog-api-key",
}

# Query parameters that indicate credentials
CREDENTIAL_PARAMS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "key",
    "auth",
}


class EgressProxy:
    r"""Domain-allowlist egress proxy with credential stripping and server-side injection.

    Every sandbox network request passes through this proxy. The proxy:
      1. Validates the target domain against the allowlist
      2. Strips any credential headers the sandbox code might have set
      3. Injects the correct server-side credentials for the matched domain
      4. Rate-limits per-domain requests

    Usage:
        proxy = EgressProxy()
        proxy.add_rule(EgressRule(
            domain_pattern=r".*\.github\.com$",
            inject_headers={"Authorization": "token ghp_xxx"},
            description="GitHub API access"
        ))

        decision = proxy.evaluate("https://api.github.com/repos/x/y", method="GET", headers={...})
        if decision.allowed:
            # Forward with decision.injected_headers
            ...
    """

    def __init__(self) -> None:
        self._rules: List[EgressRule] = []
        self._compiled_patterns: List[re.Pattern] = []

        # Rate limiting: domain -> (count, window_start)
        self._rate_counters: Dict[str, tuple[int, float]] = {}

        # Audit log
        self._audit: List[dict] = []

    def add_rule(self, rule: EgressRule) -> None:
        """Register a domain allowlist rule."""
        self._rules.append(rule)
        self._compiled_patterns.append(re.compile(rule.domain_pattern, re.IGNORECASE))
        logger.info(f"🌐 Egress rule added: {rule.domain_pattern} — {rule.description}")

    def remove_all_rules(self) -> None:
        """Clear all egress rules."""
        self._rules.clear()
        self._compiled_patterns.clear()

    def evaluate(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, str]] = None,
    ) -> EgressDecision:
        """Evaluate an outbound request against the allowlist.

        Args:
            url: Target URL
            method: HTTP method
            headers: Request headers (will be stripped of credentials)
            query_params: URL query parameters (will be stripped of credentials)

        Returns:
            EgressDecision indicating if the request is allowed and what
            headers to inject server-side.
        """
        domain = self._extract_domain(url)
        method_upper = method.upper()
        now = time.time()

        # 1. Find matching rule
        matched_rule = None
        matched_idx = -1
        for idx, (rule, pattern) in enumerate(zip(self._rules, self._compiled_patterns)):
            if pattern.match(domain) and method_upper in rule.methods:
                matched_rule = rule
                matched_idx = idx
                break

        if not matched_rule:
            decision = EgressDecision(
                allowed=False,
                reason=f"Domain '{domain}' is not in the egress allowlist."
            )
            self._log_audit(url, method, domain, decision)
            return decision

        # 2. Rate limiting
        counter_key = f"{matched_idx}:{domain}"
        count, window_start = self._rate_counters.get(counter_key, (0, now))
        if now - window_start > 60:
            count = 0
            window_start = now
        count += 1
        self._rate_counters[counter_key] = (count, window_start)

        if count > matched_rule.max_requests_per_min:
            decision = EgressDecision(
                allowed=False,
                matched_rule=matched_rule.domain_pattern,
                reason=f"Rate limit exceeded for domain '{domain}' ({count}/{matched_rule.max_requests_per_min} per min)."
            )
            self._log_audit(url, method, domain, decision)
            return decision

        # 3. Strip credential headers from sandbox request
        stripped = self._strip_credentials(headers or {}, query_params or {})

        # 4. Inject server-side credentials
        decision = EgressDecision(
            allowed=True,
            matched_rule=matched_rule.domain_pattern,
            reason="Allowed by egress rule.",
            injected_headers=dict(matched_rule.inject_headers),
        )

        self._log_audit(url, method, domain, decision)
        return decision

    def _extract_domain(self, url: str) -> str:
        """Extract the domain from a URL."""
        # Simple extraction without urllib to keep it lightweight
        url = url.split("://", 1)[-1]  # Remove scheme
        domain = url.split("/", 1)[0]   # Remove path
        domain = domain.split(":", 1)[0]  # Remove port
        return domain.lower()

    def _strip_credentials(
        self,
        headers: Dict[str, str],
        query_params: Dict[str, str],
    ) -> dict:
        """Remove credential headers and query parameters.

        Returns a dict of what was stripped (for audit logging).
        """
        stripped = {"headers": [], "params": []}

        for key in list(headers.keys()):
            if key.lower() in CREDENTIAL_HEADERS:
                stripped["headers"].append(key)
                del headers[key]

        for key in list(query_params.keys()):
            if key.lower() in CREDENTIAL_PARAMS:
                stripped["params"].append(key)
                del query_params[key]

        if stripped["headers"] or stripped["params"]:
            logger.info(f"🛡️ Credential stripping: removed {stripped}")

        return stripped

    def _log_audit(self, url: str, method: str, domain: str, decision: EgressDecision) -> None:
        """Log egress decision for audit trail."""
        entry = {
            "timestamp": time.time(),
            "url": url,
            "method": method,
            "domain": domain,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
        }
        self._audit.append(entry)

        # Keep bounded
        if len(self._audit) > 10000:
            self._audit = self._audit[-5000:]

    def get_audit_log(self, limit: int = 100) -> List[dict]:
        """Return recent egress audit entries."""
        return self._audit[-limit:]

    def get_rules(self) -> List[dict]:
        """Return current rules."""
        return [
            {
                "domain_pattern": r.domain_pattern,
                "methods": list(r.methods),
                "max_requests_per_min": r.max_requests_per_min,
                "description": r.description,
                "has_injected_credentials": bool(r.inject_headers),
            }
            for r in self._rules
        ]

    def get_stats(self) -> dict:
        """Return proxy statistics."""
        allowed_count = sum(1 for e in self._audit if e["allowed"])
        denied_count = sum(1 for e in self._audit if not e["allowed"])
        return {
            "total_rules": len(self._rules),
            "total_evaluations": len(self._audit),
            "allowed": allowed_count,
            "denied": denied_count,
        }
