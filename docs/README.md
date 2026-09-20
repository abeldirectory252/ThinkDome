# ThinkDome Documentation Hub

Welcome to the comprehensive documentation for **ThinkDome** — the multi-backend code execution sandbox, security boundary, and agent orchestration platform.

---

## 📚 Documentation Map

```
docs/
├── README.md                      # Documentation Hub & Sitemap (You are here)
├── thinkdome.png                  # Platform architecture visual
├── architecture/
│   ├── ARCHITECTURE.md            # Complete system architecture with Mermaid diagrams
│   ├── dynamic_ui_framework.md   # Dynamic UI builder & desk schema specification
│   └── multi_tenant_sandbox.md    # Multi-tenancy isolation and database routing
├── api/
│   └── API_REFERENCE.md           # REST endpoints, WebSockets, MCP schemas, Python SDK
├── guides/
│   └── GETTING_STARTED.md         # Onboarding, installation, CLI, server setup & troubleshooting
├── isolation/
│   ├── docker.md                  # Docker container isolation specifications
│   └── DockerRes.md               # Docker resource limits & cgroups configurations
├── integrations/
│   └── langgraph.md               # LangGraph state checkpoints and orchestration
├── example/
│   ├── hypervisor_setup_guide.md  # Setting up KVM, Firecracker, and MicroVMs
│   ├── credential_vault.md        # Secure credential injection & zero-leak vault
│   ├── network_policy.md          # Egress traffic filtering and domain allowlists
│   └── secure_container_runtime.md# Low-level container runtime parameters
└── changelog/
    └── COMMIT_HISTORY.md          # Full categorized git commit history
```

---

## 🚀 Quick Navigation

### 1. New to ThinkDome?
- Check out the [Getting Started Guide](guides/GETTING_STARTED.md) for quick setup, CLI commands, and running your first sandbox.
- Read [System Architecture](architecture/ARCHITECTURE.md) to understand how the control plane, executors, and security boundaries interact.

### 2. Building Integrations & Agents?
- Explore the [API Reference](api/API_REFERENCE.md) for REST endpoints, WebSocket streaming, and Python SDK.
- Learn how to integrate [LangGraph Workflows](integrations/langgraph.md) with persistent checkpoints.
- Use [Credential Vault](example/credential_vault.md) to safely inject secrets into sandboxes.

### 3. Securing & Hardening Deployments?
- Learn about [Docker Isolation](isolation/docker.md) and [Docker Resource Allocation](isolation/DockerRes.md).
- Configure [Network Egress Policies](example/network_policy.md) with default-deny rules.
- Set up hardware-assisted virtualization with the [Hypervisor Setup Guide](example/hypervisor_setup_guide.md).

### 4. History & Changelog
- Browse all past updates and release changes in the [Commit History](changelog/COMMIT_HISTORY.md).
