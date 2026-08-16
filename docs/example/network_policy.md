# Network Policy & Ingress/Egress Control Guide

ThinkDome provides per-sandbox outbound network egress policy enforcement, unified multi-strategy ingress routing, and cryptographically signed URL route tokens matching OpenSandbox specifications.

---

## 🔒 Outbound Egress Network Policy

Egress traffic from sandboxes is controlled by a `NetworkPolicy`. The policy specifies a `defaultAction` (`"deny"` or `"allow"`) and a list of `NetworkRule` definitions evaluated in order.

### Python SDK Usage Example

```python
from datetime import timedelta
from thinkdome import Sandbox
from thinkdome.sandbox import SandboxImageSpec, CredentialProxyConfig
from thinkdome.execution.network.policy import NetworkPolicy, NetworkRule

# Create sandbox with strict default-deny egress and explicit allow rules
sandbox = Sandbox.create(
    image=SandboxImageSpec(uri="opensandbox/code-interpreter:latest"),
    timeout=timedelta(minutes=15),
    network_policy=NetworkPolicy(
        defaultAction="deny",
        egress=[
            NetworkRule(
                action="allow",
                target="api.anthropic.com",
                ports=[443],
                protocols=["tcp"],
            ),
            NetworkRule(
                action="allow",
                target="pypi.org",
                ports=[80, 443],
            ),
            NetworkRule(
                action="allow",
                target="*.pythonhosted.org",
                ports=[443],
            ),
        ],
    ),
    credential_proxy=CredentialProxyConfig(enabled=True),
)

try:
    # Run code with network policy active
    result = sandbox.run("import urllib.request; print(urllib.request.urlopen('https://pypi.org').status)")
    print("Execution output:", result.output)
finally:
    sandbox.kill()
```

---

## 🌐 Unified Ingress Gateway

The ThinkDome Ingress Gateway exposes 3 complementary routing strategies for accessing sandbox services:

### 1. Header Strategy
Inject the target header `ThinkDome-Ingress-To` or `OpenSandbox-Ingress-To`:

```http
GET /api/v1/resource HTTP/1.1
Host: gateway.thinkdome.internal
ThinkDome-Ingress-To: sb_abc123:8080
```

### 2. URI Path Strategy
Route via the proxy path prefix:

```http
GET /sandboxes/sb_abc123/proxy/8080/v1/health HTTP/1.1
Host: gateway.thinkdome.internal
```

### 3. Wildcard Subdomain Strategy
Route via host subdomain labels:

```http
GET /index.html HTTP/1.1
Host: sb_abc123-8080.sandboxes.thinkdome.internal
```

---

## 🔑 Cryptographically Signed Route Tokens (OSEP-0011)

For public or web-facing sandbox endpoints, generate OSEP-0011 signed route tokens to prevent unauthorized route forgery:

```python
import time
from thinkdome.execution.network.signing import build_signed_route, verify_signed_route

# Server secret key
secret_key = b"super_secret_signing_key_hex_or_bytes"

# Generate signed route token expiring in 1 hour
token = build_signed_route(
    sandbox_id="sb_agent_42",
    port=8080,
    expires_sec=int(time.time()) + 3600,
    secret_bytes=secret_key,
    key_id="a",
)

# Generated Token format: sb_agent_42-8080-1a2b3c-sig12345a
print("Signed Route Token:", token)

# Accessing endpoint with signed token via Header or URI:
# Header: ThinkDome-Ingress-To: sb_agent_42-8080-1a2b3c-sig12345a
# URI: /sandboxes/sb_agent_42/8080/1a2b3c/sig12345a/app
```

---

## 📊 Network Audit Logging & REST APIs

All network egress decisions are logged in real-time and exposed via REST APIs:

- **Egress Audit Logs**: `GET /v1/network/audit-log?limit=100&sandbox_id=sb_abc123`
- **Egress Statistics**: `GET /v1/network/stats`
- **Active Domain Rules**: `GET /v1/network/rules`

```bash
# Fetch recent network egress audit logs
curl -s http://localhost:8080/v1/network/audit-log?limit=10 | jq .
```
