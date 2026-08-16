# ThinkDome 🧠📦

> Secure, isolated multi-backend code execution sandbox and tool orchestrator for autonomous AI agents and applications.

`thinkdome` is a production-grade execution sandbox and security engine designed for LLMs, agentic workflows, and safe code execution. It can be used directly as a **Python SDK** or as a **FastAPI server** with a suite of tools, native privilege checks, strict egress network policies, and real-time audit dashboards.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/notebook/thinkdome_kaggle.ipynb)
[![Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)](https://kaggle.com/kernels/welcome?src=https://github.com/abeldirectory252/ThinkDome/blob/main/notebook/thinkdome_kaggle.ipynb)

---

## 🏗️ Architecture & Domain Structure

`thinkdome` follows a domain-driven module architecture:

```
thinkdome/
├── api/                     # REST/HTTP API layer (FastAPI app factory & routes)
├── sandbox/                 # Sandbox domain (SDK, MicroVM/Docker/gVisor backends, network, pool, sessions)
│   ├── sdk.py               # Main Sandbox SDK entry point
│   ├── executors/           # MicroVM (Firecracker), Docker, gVisor, Kata, Host backends
│   ├── network/             # Ingress gateway, Egress proxy, Policy enforcement, Signing
│   ├── pool/                # Pre-warmed container/VM pool manager
│   ├── sessions/            # Persistent sandbox session manager
│   └── snapshots/           # Snapshot creation & backtrack state restoration
├── platform/                # Platform services (Billing, Storage, Tasks, Database, Observability, Orchestration)
├── security/                # Cross-cutting security (Auth, Identity, RBAC, Vulnerability scanner, Vault)
├── core/                    # Core framework plumbing (Config, Middleware, ORM, Events, Logging)
├── apps/                    # Business applications (ERP, Agents, Marketplace, Workflows)
└── static/                  # Web UI Dashboard & Real-Time Analytics
```

---

## ⚡ Execution Backends

`thinkdome` supports multiple hypervisor and container runtimes based on your isolation and performance requirements:

| Backend | Technology | Isolation Level | Cold Start | Use Case |
|---|---|---|---|---|
| **`microvm`** | Firecracker MicroVM | Hardware Virtualization (KVM) | ~50ms | Maximum multi-tenant security |
| **`gvisor`** | gVisor (runsc) | User-space Kernel Isolation | ~100ms | Untrusted code execution |
| **`kata`** | Kata Containers | Lightweight VM Isolation | ~300ms | Hardware isolation with Docker compatibility |
| **`docker`** | Docker (cgroups v2 + seccomp) | OS Container Virtualization | ~200ms | Standard container workloads |
| **`subprocess`**| Bubblewrap / Subprocess | Process Isolation | ~5ms | Fast local development / testing fallback |

Set backend via SDK:
```python
from thinkdome import Sandbox

with Sandbox(backend="microvm") as dome:
    result = dome.run("import platform; print(platform.uname())")
    print(result.output)
```

---

## 🌐 Network Control & Egress Policies

`thinkdome` features a **strict default-deny network policy**:

- **Default-Deny Policy**: All outbound network traffic is blocked by default (`defaultAction="deny"`).
- **Explicit Domain Allowlisting**: Outbound requests are allowed only to explicitly registered FQDNs and rules (e.g. PyPI, GitHub API).
- **Non-Bypassable Egress Proxy**: Traffic is intercepted by the `EgressProxy` with SNI inspection and request throttling.
- **Ingress Gateway**: Signed request signatures and token validation for incoming agent calls.
- **Real-Time Audit Log & Analytics**: All outbound connection attempts (allowed and denied) are logged and exposed via REST APIs (`/v1/network/audit-log`, `/stats`, `/rules`) and the Web Dashboard.

```python
from thinkdome import Sandbox
from thinkdome.sandbox.network import EgressRule

# Sandbox with custom network egress allowlist
with Sandbox(
    allow_network=True,
    egress_rules=[
        EgressRule(domain="api.github.com", action="allow", ports=[443]),
        EgressRule(domain="pypi.org", action="allow", ports=[443]),
    ]
) as dome:
    res = dome.run("import urllib.request; print(urllib.request.urlopen('https://api.github.com').status)")
    print(res.output)
```

---

## 🐍 Python SDK Usage

```python
from thinkdome import Sandbox

# Run untrusted code in an ephemeral sandbox
with Sandbox() as dome:
    # Write files before execution
    dome.write_file("data.csv", "name,value\nAlice,10\nBob,20\n")
    
    # Execute code safely
    result = dome.run("""
import pandas as pd
df = pd.read_csv('data.csv')
print("Total Sum:", df['value'].sum())
""")
    
    print("Success:", result.success)
    print("Stdout:", result.output.strip())
    print("Files in workspace:", dome.list_files())
```

---

## 🖥️ Command Line & API Server

### Start API Server & Web UI
```bash
thinkdome serve --host 127.0.0.1 --port 8000
```
Open `http://localhost:8000` to view the interactive **Network Egress & Sandbox Dashboard**.

### Run Code via CLI
```bash
thinkdome run "print('Hello from CLI!')" --backend microvm
```

---

## 🛡️ Defense-in-Depth Containment

1. **MicroVM / gVisor Hypervisor**: Hardware KVM boundaries prevent host kernel exploit paths.
2. **Non-Root Execution**: Runs under unprivileged user (`UID 1000:1000`).
3. **Read-Only Root Filesystem**: Write access restricted to ephemeral RAM-disk `/workspace` (`tmpfs`).
4. **Seccomp System Call Filtering**: Blocks dangerous syscalls (`mount`, `ptrace`, `bpf`, `io_uring`).
5. **Resource Limits**: `0.5 CPU` cores, `256MB RAM`, `20 PIDs` max (prevent fork bombs).
6. **Capability Dropping**: Drops all Linux capabilities (`cap_drop=["ALL"]`).
7. **Egress Firewall**: Strict domain allowlisting and real-time audit logging.

---

## 🧪 Verification & Testing

Run full test suite:
```bash
pytest tests/ -v
```
