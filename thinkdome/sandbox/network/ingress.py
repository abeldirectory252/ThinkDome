"""Unified Ingress Gateway for ThinkDome.

Implements all 3 OpenSandbox ingress routing strategies:
  1. Wildcard Subdomain Strategy:
     Host: <sandbox_id>-<port>.<domain> OR <sandbox_id>-<port>-<expires_b36>-<signature>.<domain>
  2. Header Strategy:
     Header 'ThinkDome-Ingress-To' or 'OpenSandbox-Ingress-To': <sandbox_id>:<port> or <token>
  3. URI Path Strategy:
     Path: /sandboxes/<sandbox_id>/proxy/<port>/<path> OR /sandboxes/<sandbox_id>/<port>/<expires_b36>/<signature>/<path>

Parses and validates OSEP-0011 signed route tokens when present.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from fastapi import Request, HTTPException, status

from thinkdome.sandbox.network.signing import verify_signed_route

logger = logging.getLogger(__name__)

THINKDOME_INGRESS_HEADER = "ThinkDome-Ingress-To"
OPENSANDBOX_INGRESS_HEADER = "OpenSandbox-Ingress-To"


class RoutingStrategy(str, Enum):
    WILDCARD = "wildcard"
    HEADER = "header"
    URI = "uri"


@dataclass
class IngressRoute:
    """Resolved ingress route target."""
    sandbox_id: str
    port: int
    strategy_used: RoutingStrategy
    expires_b36: str = ""
    signature: str = ""
    target_path: str = "/"
    is_signed: bool = False
    is_valid_signature: bool = True
    reject_reason: str = ""


class IngressGateway:
    """Unified Ingress Gateway supporting Wildcard, Header, and URI routing.

    Usage:
        gateway = IngressGateway(secret_keys={"a": b"my_secret"})
        route = gateway.resolve_route(request)
        if not route.is_valid_signature:
            raise HTTPException(403, detail=route.reject_reason)
    """

    def __init__(
        self,
        secret_keys: Optional[Dict[str, bytes]] = None,
        wildcard_domain: Optional[str] = None,
    ) -> None:
        self.secret_keys = secret_keys or {}
        self.wildcard_domain = wildcard_domain

    def resolve_route(self, request: Request) -> IngressRoute:
        """Resolve target sandbox route from HTTP request using 3 strategies in order.

        Priority:
          1. Header strategy (if ThinkDome-Ingress-To / OpenSandbox-Ingress-To present)
          2. URI path strategy (if path matches /sandboxes/{id}/proxy/... or /{id}/{port}/{b36}/{sig}/...)
          3. Wildcard subdomain strategy (if Host header contains <sb_id>-<port>.<domain>)
        """
        # 1. Header Strategy
        header_val = (
            request.headers.get(THINKDOME_INGRESS_HEADER)
            or request.headers.get(OPENSANDBOX_INGRESS_HEADER)
        )
        if header_val:
            return self._parse_header_route(header_val.strip(), request)

        # 2. URI Strategy
        path = request.url.path
        uri_route = self._parse_uri_route(path, request)
        if uri_route:
            return uri_route

        # 3. Wildcard Subdomain Strategy
        host_header = request.headers.get("host", "").split(":")[0]
        if host_header:
            wildcard_route = self._parse_wildcard_route(host_header, request)
            if wildcard_route:
                return wildcard_route

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "INGRESS::ROUTE_NOT_FOUND",
                "message": f"Unable to resolve ingress route for request path '{path}'.",
            },
        )

    # ── Strategy Parsers ───────────────────────────────────────────────────────

    def _parse_header_route(self, header_val: str, request: Request) -> IngressRoute:
        """Parse ThinkDome-Ingress-To header: 'sb_123:8080' or signed token 'sb_123-8080-1a2b-sig'."""
        if ":" in header_val:
            parts = header_val.split(":", 1)
            try:
                port = int(parts[1])
                return IngressRoute(
                    sandbox_id=parts[0],
                    port=port,
                    strategy_used=RoutingStrategy.HEADER,
                    target_path=request.url.path,
                )
            except ValueError:
                pass

        # Try signed route token
        return self._verify_or_create_route(
            token_str=header_val,
            strategy=RoutingStrategy.HEADER,
            target_path=request.url.path,
        )

    def _parse_uri_route(self, path: str, request: Request) -> Optional[IngressRoute]:
        """Parse path-based route:
        - Legacy: /sandboxes/{id}/proxy/{port}/{rest}
        - OSEP path: /sandboxes/{id}/{port}/{expires_b36}/{sig}/{rest}
        """
        # Legacy proxy route: /sandboxes/{id}/proxy/{port}/...
        if "/proxy/" in path:
            m = re.match(r"^/sandboxes/([^/]+)/proxy/(\d+)(/.*)?$", path)
            if m:
                sb_id = m.group(1)
                port = int(m.group(2))
                target_path = m.group(3) or "/"
                return IngressRoute(
                    sandbox_id=sb_id,
                    port=port,
                    strategy_used=RoutingStrategy.URI,
                    target_path=target_path,
                )

        # OSEP path route: /sandboxes/{id}/{port}/{expires_b36}/{sig}/...
        m_osep = re.match(r"^/sandboxes/([^/]+)/(\d+)/([^/]+)/([^/]+)(/.*)?$", path)
        if m_osep:
            sb_id = m_osep.group(1)
            port = int(m_osep.group(2))
            expires_b36 = m_osep.group(3)
            sig = m_osep.group(4)
            target_path = m_osep.group(5) or "/"

            token = f"{sb_id}-{port}-{expires_b36}-{sig}"
            route = self._verify_or_create_route(
                token_str=token,
                strategy=RoutingStrategy.URI,
                target_path=target_path,
            )
            return route

        return None

    def _parse_wildcard_route(self, host: str, request: Request) -> Optional[IngressRoute]:
        """Parse host header: '<sandbox-id>-<port>.<domain>' or '<signed_token>.<domain>'."""
        label = host.split(".")[0]
        if not label:
            return None

        # Check if label contains dashes
        parts = label.split("-")
        if len(parts) < 2:
            return None

        # Signed route token has >= 4 parts: sb_id-port-expires_b36-sig
        if len(parts) >= 4:
            return self._verify_or_create_route(
                token_str=label,
                strategy=RoutingStrategy.WILDCARD,
                target_path=request.url.path,
            )

        # Unsigned route: sb_id-port
        try:
            port = int(parts[-1])
            sb_id = "-".join(parts[:-1])
            return IngressRoute(
                sandbox_id=sb_id,
                port=port,
                strategy_used=RoutingStrategy.WILDCARD,
                target_path=request.url.path,
            )
        except ValueError:
            return None

    # ── Token Verification Helper ──────────────────────────────────────────────

    def _verify_or_create_route(
        self,
        token_str: str,
        strategy: RoutingStrategy,
        target_path: str,
    ) -> IngressRoute:
        import time

        if not self.secret_keys:
            # Fallback when secret_keys is unconfigured: parse token without signature check
            parts = token_str.split("-")
            if len(parts) >= 4:
                try:
                    port = int(parts[-3])
                    sb_id = "-".join(parts[:-3])
                    return IngressRoute(
                        sandbox_id=sb_id,
                        port=port,
                        strategy_used=strategy,
                        expires_b36=parts[-2],
                        signature=parts[-1],
                        target_path=target_path,
                        is_signed=True,
                        is_valid_signature=True,
                    )
                except ValueError:
                    pass

        now_sec = int(time.time())
        valid, reason, sb_id, port = verify_signed_route(
            token_str,
            secret_keys=self.secret_keys,
            current_time_sec=now_sec,
        )

        parts = token_str.split("-")
        expires_b36 = parts[-2] if len(parts) >= 4 else ""
        sig = parts[-1] if len(parts) >= 4 else ""

        return IngressRoute(
            sandbox_id=sb_id or token_str,
            port=port or 80,
            strategy_used=strategy,
            expires_b36=expires_b36,
            signature=sig,
            target_path=target_path,
            is_signed=True,
            is_valid_signature=valid,
            reject_reason=reason,
        )
