import json
import ipaddress
import socket
from urllib.parse import urlparse
from typing import Any
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.orchestrator_models import HttpRequestInput


def _is_private_or_internal_host(host: str) -> bool:
    """Return True if host resolves to a private, loopback, or cloud metadata IP."""
    host_lower = host.lower().strip()
    if host_lower in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254", "metadata.google.internal"}:
        return True

    try:
        ip = ipaddress.ip_address(host_lower)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        pass

    # Resolve hostname
    try:
        addrs = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in addrs:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                    return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


@register_tool
class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Send outbound HTTP requests to APIs"
    required_scope = "network:all"
    input_schema = HttpRequestInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        url = tool_input.get("url")
        if not url:
            raise ValueError("Parameter 'url' is required for http_request.")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")

        hostname = parsed.hostname
        if not hostname or _is_private_or_internal_host(hostname):
            raise PermissionError(f"Access denied: URL '{url}' attempts access to private/internal network resource.")

        method = (tool_input.get("method", "GET")).upper()
        headers = dict(tool_input.get("headers") or {})
        body = tool_input.get("body")
        timeout = min(tool_input.get("timeout", 30), 120)

        # Check egress proxy if context available
        ctx = get_context()
        if hasattr(ctx, "egress_proxy") and ctx.egress_proxy:
            decision = ctx.egress_proxy.evaluate(url, method=method, headers=headers, sandbox_id=ctx.sandbox_id)
            if not decision.allowed:
                raise PermissionError(f"Egress policy denied request: {decision.reason}")
            headers.update(decision.injected_headers)

        settings = get_settings()

        # Ignore ambient HTTP(S)_PROXY/NO_PROXY variables: allowing them to
        # influence this client would bypass the sandbox egress decision.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

        body_text = response.text[:settings.MAX_OUTPUT_BYTES]
        return json.dumps({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body_text,
            "url": str(response.url),
            "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 2)
        })
