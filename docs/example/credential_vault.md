# Credential Vault & Outbound Secret Brokerage Guide

Credential Vault is ThinkDome's outbound secret broker. Real API keys and credentials are stored securely server-side in Vault, while the sandbox workload process only receives dummy or placeholder values.

When tools inside the sandbox make outbound HTTPS requests, Credential Vault matches the request against bindings and injects real authentication headers or replaces placeholders on the fly.

---

## 🔐 Auth Injection Types

1. **`bearer`**: Injects `Authorization: Bearer <credential>`
2. **`basic`**: Injects `Authorization: Basic <base64(user:pass)>`
3. **`apiKey`**: Injects `<header_name>: <credential>`
4. **`customHeaders`**: Injects multiple header mappings
5. **`passthrough`**: Performs scoped placeholder substitutions without adding auth headers

---

## 💡 Example 1: Claude Code with Anthropic API Key Injection

The host environment holds the real `ANTHROPIC_API_KEY`, while the sandbox process only sees a dummy key `fake-key-inside-sandbox`.

```python
import os
from datetime import timedelta
from thinkdome import Sandbox
from thinkdome.sandbox import SandboxImageSpec, CredentialProxyConfig
from thinkdome.execution.network.policy import NetworkPolicy, NetworkRule
from thinkdome.security.auth.vault_bindings import Credential, CredentialBinding

REAL_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-real-key-12345")

# 1. Create sandbox with Credential Proxy enabled
sandbox = Sandbox.create(
    image=SandboxImageSpec(uri="opensandbox/code-interpreter:latest"),
    timeout=timedelta(minutes=15),
    env={
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        "ANTHROPIC_API_KEY": "fake-key-inside-sandbox",
    },
    network_policy=NetworkPolicy(
        defaultAction="deny",
        egress=[
            NetworkRule(action="allow", target="api.anthropic.com"),
            NetworkRule(action="allow", target="registry.npmjs.org"),
        ],
    ),
    credential_proxy=CredentialProxyConfig(enabled=True),
)

try:
    # 2. Register real secret in Vault & define binding
    sandbox.register_vault_credentials(
        credentials=[
            Credential(name="anthropic-key", source={"value": REAL_API_KEY})
        ],
        bindings=[
            CredentialBinding(
                name="anthropic-api",
                match={
                    "schemes": ["https"],
                    "hosts": ["api.anthropic.com"],
                    "methods": ["GET", "POST"],
                    "paths": ["/v1/*"],
                },
                auth={
                    "type": "apiKey",
                    "name": "x-api-key",
                    "credential": "anthropic-key",
                },
            )
        ],
    )

    # 3. Execute secret-free code in sandbox
    result = sandbox.run("npm install -g @anthropic-ai/claude-code && claude -p '1+1'")
    print(result.output)
finally:
    sandbox.kill()
```

---

## 🔄 Example 2: Scoped Placeholder Substitutions

Use placeholders like `__api_key__` in query parameters or request bodies without placing real secrets in the sandbox filesystem or command arguments:

```python
from thinkdome.security.auth.vault_bindings import CredentialBinding, AuthRule, SubstitutionRule

binding = CredentialBinding(
    name="token-request",
    match={
        "schemes": ["https"],
        "hosts": ["api.example.com"],
        "methods": ["POST"],
        "paths": ["/v1/tokens"],
    },
    auth={
        "type": "passthrough",
        "substitutions": [
            {
                "credential": "api-secret-key",
                "placeholder": "__api_secret__",
                "in": ["body", "query"],
            }
        ],
    },
)
```
