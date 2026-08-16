# ThinkDome 🧠📦

> Secure, isolated multi-backend code execution sandbox and tool orchestrator for autonomous AI agents and applications.

`thinkdome` is a production-grade execution sandbox and security engine designed for LLMs, agentic workflows, and safe code execution. It can be used directly as a **Python SDK** or as a **FastAPI server** with a suite of tools, native privilege checks, strict egress network policies, and real-time audit dashboards.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)
[![Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)](https://kaggle.com/kernels/welcome?src=https://github.com/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)

---

## ⚡ Quickstart via `pip install` (Try in Google Colab)

Install ThinkDome directly from GitHub in **Google Colab**, **Kaggle**, or any Python environment with a single command:

```bash
pip install git+https://github.com/abeldirectory252/ThinkDome.git
```

### Try Live Notebook in Google Colab
Click the badge below to launch the pre-configured interactive notebook directly in **Google Colab**:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)

### CLI Quickstart
```bash
# 1. Run system readiness check
thinkdome check

# 2. Execute code in isolated sandbox
thinkdome run "import sys; print('Hello from ThinkDome!'); print(sys.version)"

# 3. Start API Server & Web Console UI
thinkdome serve --host 0.0.0.0 --port 8000
```

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

### MicroVM & Non-Root Setup Guide

> 📘 **Full Hypervisor & Secure Container Installation Guide**: For detailed instructions on downloading, installing, and configuring gVisor (`runsc`), Kata Containers, Firecracker, Cloud Hypervisor, Docker integration (`/etc/docker/daemon.json`), and kernel/rootfs assets, see the [Hypervisor & Secure Container Setup Guide](file:///home/sandbox/ThinkDome/docs/example/hypervisor_setup_guide.md).

To run hardware-virtualized MicroVM sandboxes (`cloud-hypervisor` or `firecracker`), `thinkdome` requires the hypervisor binary and guest OS assets:


#### 1. Install Hypervisor Binary
Download the static release binary into your `PATH`:
```bash
mkdir -p ~/.local/bin
curl -L https://github.com/cloud-hypervisor/cloud-hypervisor/releases/download/v40.0/cloud-hypervisor -o ~/.local/bin/cloud-hypervisor
chmod +x ~/.local/bin/cloud-hypervisor
```

#### 2. KVM & Kernel/Rootfs Setup
- **KVM Access**: Ensure `/dev/kvm` is accessible: `sudo chmod 666 /dev/kvm` (or add your user to `kvm` group: `sudo usermod -aG kvm $USER`).
- **Guest OS Assets**: Place guest kernel and ext4 filesystem images at default locations (or configure via environment variables):
  - Kernel: `/var/lib/thinkdome/vmlinux` (`MICROVM_KERNEL_PATH`)
  - Rootfs: `/var/lib/thinkdome/rootfs.ext4` (`MICROVM_ROOTFS_PATH`)

#### 3. Execution Modes

Choose the execution mode suited for your environment:

- **Mode A: Dev / Unprivileged Non-Root (with Automatic Fallback)**:
  Runs using process/subprocess or container fallback when KVM/TAP permissions are missing:
  ```bash
  EXECUTOR_BACKEND_USE_FALLBACK=True ./venv/bin/python -m thinkdome.cli serve
  ```

- **Mode B: Docker / Kata / gVisor Runtime (`backend="docker"`)**:
  Docker handles container/VM network namespaces without host TAP creation:
  ```bash
  EXECUTOR_BACKEND=docker ./venv/bin/python -m thinkdome.cli serve
  ```

- **Mode C: Native Host MicroVM (Root / `CAP_NET_ADMIN`)**:
  Provides direct host TAP device bridging for production multi-tenant isolation:
  ```bash
  sudo ./venv/bin/python -m thinkdome.cli serve
  # or: sudo setcap cap_net_admin,cap_net_raw+ep $(which python3)
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

You can configure the server using environment variables (`HOST`, `PORT`, `EXECUTOR_BACKEND`, `EXECUTOR_BACKEND_USE_FALLBACK`) or command-line flags:

```bash
# Direct inline environment variables
HOST=127.0.0.1 PORT=8000 EXECUTOR_BACKEND=microvm ./venv/bin/thinkdome serve

# Or using exported environment variables
export HOST="127.0.0.1"
export PORT="8000"
export EXECUTOR_BACKEND="microvm"             # "microvm" | "docker" | "kubernetes" | "subprocess"
export EXECUTOR_BACKEND_USE_FALLBACK="True"   # Set True for auto-fallback to subprocess in dev/non-root

./venv/bin/thinkdome serve --host 127.0.0.1 --port 8000
```

> **Note**: You can also run directly using the virtual environment Python executable:
> ```bash
> ./venv/bin/python -m thinkdome.cli serve --host 127.0.0.1 --port 8000
> ```

Open `http://localhost:8000` to view the interactive **Network Egress & Sandbox Dashboard**.

### Run Code via CLI

```bash
# Execute via virtualenv thinkdome CLI binary
EXECUTOR_BACKEND=microvm ./venv/bin/thinkdome run "print('Hello from CLI!')" --backend microvm

# Or via virtualenv python module syntax:
./venv/bin/python -m thinkdome.cli run "print('Hello from CLI!')" --backend subprocess
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
