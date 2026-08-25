<div align="center">

# ThinkDome

### Secure, isolated multi-backend code execution sandbox and tool orchestrator for autonomous AI agents and applications.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)
[![Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)](https://kaggle.com/kernels/welcome?src=https://github.com/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)

<p align="center">
  <img src="https://github.com/abeldirectory252/ThinkDome/blob/main/docs/thinkdome.png" alt="ThinkDome Sandbox" width="700">
</p>

</div>

---

## 📌 Overview

**ThinkDome** is a secure, isolated code execution sandbox and tool orchestration platform designed for **autonomous AI agents, applications, and multi-tenant workloads**.

It provides multiple execution backends with different levels of isolation, allowing applications to run untrusted or dynamically generated code inside controlled environments.

ThinkDome supports:

* 🐍 Python SDK for programmatic sandbox execution
* 💻 Command-line interface
* 🌐 API server and web dashboard
* 🐳 Docker container isolation
* 🔥 Firecracker and MicroVM execution
* 🛡️ gVisor user-space kernel isolation
* 📦 Kata Containers support
* ⚡ Fast subprocess-based execution for development
* 🌐 Default-deny network policies and egress control
* 📊 Network audit logging and analytics
* 🏢 Multi-tenant site management tools

---

## ⚡ Quick Start

### Install from GitHub

Install ThinkDome directly from GitHub:

```bash
pip install git+https://github.com/abeldirectory252/ThinkDome.git
```

You can use this in **Google Colab**, **Kaggle**, or any supported Python environment.

### Verify Your Environment

Run the system readiness check:

```bash
thinkdome check
```

### Run Your First Sandbox

```bash
thinkdome run 'print("Hello from ThinkDome!")' --backend subprocess
```

---

## ⚡ Try in Google Colab

Open the interactive quickstart notebook:

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/ThinkDome_Colab_Quickstart.ipynb)

---

## ✨ Features

* **Multiple execution backends** for different security and performance requirements
* **Ephemeral sandboxes** with isolated workspaces
* **Python SDK** for agent and application integration
* **CLI tools** for local and production environments
* **API server and web dashboard**
* **Default-deny network policies**
* **Explicit domain allowlisting**
* **Network egress auditing**
* **Resource limits** for CPU, memory, and processes
* **Read-only root filesystem support**
* **Linux capability dropping**
* **Seccomp syscall filtering**
* **Multi-tenant site management**
* **Backup and restore utilities**
* **Administrator and user management tools**

---

# 🚀 CLI Quickstart

### Run Code with Different Backends

#### Subprocess

Fast process isolation for local development and testing:

```bash
thinkdome run 'print("Hello from Subprocess!")' --backend subprocess
```

#### Docker

Standard container isolation:

```bash
thinkdome run 'print("Hello from Docker!")' --backend docker
```

#### MicroVM

Hardware-virtualized isolation:

```bash
thinkdome run 'print("Hello from MicroVM!")' --backend microvm
```

#### gVisor

User-space kernel isolation:

```bash
thinkdome run 'print("Hello from gVisor!")' --backend gvisor
```

---

# 🖥️ Start the API Server

Start the ThinkDome API server and web console:

```bash
thinkdome serve --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

---

# ⚡ Execution Backends

ThinkDome supports multiple isolation technologies depending on your security and performance requirements.

| Backend          | Technology                     | Isolation Level             | Use Case                                      |
| ---------------- | ------------------------------ | --------------------------- | --------------------------------------------- |
| **`microvm`**    | Firecracker / Cloud Hypervisor | Hardware Virtualization     | Maximum isolation for multi-tenant workloads  |
| **`gvisor`**     | gVisor (`runsc`)               | User-space Kernel Isolation | Untrusted code execution                      |
| **`kata`**       | Kata Containers                | Lightweight VM Isolation    | Strong isolation with container compatibility |
| **`docker`**     | Docker + cgroups + seccomp     | OS Container Isolation      | Standard container workloads                  |
| **`subprocess`** | Bubblewrap / Subprocess        | Process Isolation           | Fast local development and testing            |

> Performance characteristics such as startup time depend on the host, image size, runtime configuration, and workload.

---

## 🐍 Python SDK

### Basic Example

```python
from thinkdome import Sandbox

with Sandbox(backend="subprocess") as dome:
    result = dome.run('print("Hello from ThinkDome!")')

    print(result.success)
    print(result.output)
```

### Docker Backend

```python
from thinkdome import Sandbox

with Sandbox(backend="docker") as dome:
    result = dome.run('print("Hello from Docker!")')
    print(result.output)
```

### MicroVM Backend

```python
from thinkdome import Sandbox

with Sandbox(backend="microvm") as dome:
    result = dome.run(
        'import platform; print(platform.uname())'
    )

    print(result.output)
```

### gVisor Backend

```python
from thinkdome import Sandbox

with Sandbox(backend="gvisor") as dome:
    result = dome.run('print("Hello from gVisor!")')
    print(result.output)
```

---

# 📁 Ephemeral Sandbox Workflow

Run code inside an isolated temporary workspace:

```python
from thinkdome import Sandbox

with Sandbox(backend="subprocess") as dome:

    # Write files into the sandbox workspace
    dome.write_file(
        "data.csv",
        "name,value\nAlice,10\nBob,20\n"
    )

    # Execute code
    result = dome.run("""
import pandas as pd

df = pd.read_csv("data.csv")
print("Total Sum:", df["value"].sum())
""")

    print("Success:", result.success)
    print("Stdout:", result.output.strip())
    print("Files:", dome.list_files())
```

---

# 🌐 Network Control and Egress Policies

ThinkDome uses a **strict default-deny network model**.

### Security Model

* **Default-Deny**: Outbound network access is blocked unless explicitly allowed.
* **Domain Allowlisting**: Allow access only to approved domains and ports.
* **Egress Control**: Network traffic can be routed through controlled egress policies.
* **Audit Logging**: Allowed and denied network requests can be recorded.
* **Ingress Protection**: Incoming requests can be protected with authentication and signature validation.
* **Resource Monitoring**: Network activity can be exposed through APIs and dashboards.

### Example

```python
from thinkdome import Sandbox
from thinkdome.sandbox.network import EgressRule

with Sandbox(
    allow_network=True,
    egress_rules=[
        EgressRule(
            domain="api.github.com",
            action="allow",
            ports=[443],
        ),
        EgressRule(
            domain="pypi.org",
            action="allow",
            ports=[443],
        ),
    ],
) as dome:

    result = dome.run("""
import urllib.request

response = urllib.request.urlopen(
    "https://api.github.com"
)

print(response.status)
""")

    print(result.output)
```

---

# 🛡️ MicroVM and Secure Runtime Setup

For hardware-virtualized MicroVM execution, ThinkDome requires a supported hypervisor and guest operating system assets.

## 1. Install a Hypervisor

Example using Cloud Hypervisor:

```bash
mkdir -p ~/.local/bin

curl -L \
  https://github.com/cloud-hypervisor/cloud-hypervisor/releases/download/v40.0/cloud-hypervisor \
  -o ~/.local/bin/cloud-hypervisor

chmod +x ~/.local/bin/cloud-hypervisor
```

Ensure the directory is available in your `PATH`.

---

## 2. Configure KVM Access

Verify that KVM is available:

```bash
ls -l /dev/kvm
```

For non-root access, add your user to the `kvm` group:

```bash
sudo usermod -aG kvm $USER
```

Log out and back in for the group change to take effect.

---

## 3. Configure Guest Assets

Configure the guest kernel and root filesystem.

Example locations:

```text
Kernel: /var/lib/thinkdome/vmlinux
Rootfs: /var/lib/thinkdome/rootfs.ext4
```

These can also be configured with environment variables:

```bash
export MICROVM_KERNEL_PATH=/var/lib/thinkdome/vmlinux
export MICROVM_ROOTFS_PATH=/var/lib/thinkdome/rootfs.ext4
```

---

# ⚙️ Execution Modes

## Mode A: Development with Automatic Fallback

Useful when KVM or network privileges are unavailable:

```bash
EXECUTOR_BACKEND_USE_FALLBACK=True \
thinkdome serve
```

---

## Mode B: Docker Runtime

Use Docker-based isolation:

```bash
EXECUTOR_BACKEND=docker \
thinkdome serve
```

---

## Mode C: Native Host MicroVM

For environments configured for native MicroVM networking:

```bash
sudo thinkdome serve
```

Production deployments should follow the principle of least privilege and grant only the capabilities required by the configured backend.

---

# 🌐 API Server Configuration

Configure ThinkDome using environment variables:

```bash
export HOST="127.0.0.1"
export PORT="8000"

export EXECUTOR_BACKEND="microvm"
export EXECUTOR_BACKEND_USE_FALLBACK="True"

thinkdome serve --host 127.0.0.1 --port 8000
```

You can also run the module directly:

```bash
python -m thinkdome.cli serve \
  --host 127.0.0.1 \
  --port 8000
```

---

# 💻 Run Code via CLI

```bash
thinkdome run \
  'print("Hello from CLI!")' \
  --backend subprocess
```

Using MicroVM:

```bash
thinkdome run \
  'print("Hello from MicroVM!")' \
  --backend microvm
```

---

# 🧰 Site Management CLI

ThinkDome includes the `think` CLI for multi-tenant site administration.

Supported operations include:

* Site backups
* Database restoration
* Public and private file restoration
* Administrator password management
* User password management
* Superadmin creation
* Interactive Python site console

---

## 💾 Site Backup

Create a timestamped backup:

```bash
think --site think.local backup
```

Example backup location:

```text
sites/think.local/private/backups/
```

View available backups:

```bash
ls -lh sites/think.local/private/backups/
```

---

## ♻️ Site Restore

Restore from a database dump:

```bash
think --site think.local restore /path/to/database.sql.gz
```

Restore the database and files:

```bash
think --site think.local restore \
  /path/to/database.sql.gz \
  --with-public-files /path/to/files.tar \
  --with-private-files /path/to/private-files.tar
```

---

## 🔐 Password Management

Reset the Administrator password:

```bash
think --site think.local set-admin-password
```

Reset a user's password:

```bash
think --site think.local set-password user@example.com
```

For production environments, prefer secure interactive prompts or secret management systems rather than placing passwords directly in shell history.

---

## 👑 Create a Superadmin

Create the Administrator account interactively:

```bash
think --site think.local create-superadmin
```

---

## 🐍 Interactive Site Console

Open a Python shell with site context:

```bash
think --site think.local console
```

Example:

```python
users = User.query().all()

admin = User.query() \
    .filter(username="administrator") \
    .first()

rows = sql(
    "SELECT username, email FROM rbac_users"
)
```

---

# 🛡️ Defense-in-Depth Containment

ThinkDome can combine multiple layers of isolation depending on the selected backend and deployment configuration:

1. **MicroVM Isolation**
   Hardware-virtualized boundaries using supported MicroVM technologies.

2. **gVisor Isolation**
   User-space kernel isolation for containerized workloads.

3. **Non-Root Execution**
   Sandboxes can run under unprivileged users.

4. **Read-Only Filesystems**
   Persistent filesystem access can be restricted while allowing temporary workspaces.

5. **Ephemeral Workspaces**
   Temporary sandbox files can be removed after execution.

6. **Seccomp Filtering**
   Restrict access to selected Linux system calls.

7. **Resource Limits**
   CPU, memory, and process limits can help prevent resource exhaustion.

8. **Capability Dropping**
   Unnecessary Linux capabilities can be removed.

9. **Network Egress Control**
   Outbound traffic can be blocked by default and explicitly allowlisted.

> **Important:** Security guarantees depend on the selected backend and your actual host configuration. `subprocess` isolation is not equivalent to a properly configured MicroVM or hardware virtualization boundary. Choose the backend according to your threat model.

---

# 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the repository
2. Create a feature branch:

```bash
git checkout -b feature/AmazingFeature
```

3. Commit your changes:

```bash
git commit -m "feat: add AmazingFeature"
```

4. Push your branch:

```bash
git push origin feature/AmazingFeature
```

5. Open a Pull Request

---

# 💬 Community and Support

* **Author:** Abel Yohannes
* **GitHub:** [@abelyo252](https://github.com/abeldirectory252/)
* **Telegram:** [@i_am_abel](https://t.me/i_am_abel)

---

# 📜 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
