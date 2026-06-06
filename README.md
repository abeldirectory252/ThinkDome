# ThinkDome 🧠📦

> Secure, isolated code execution sandbox and tool orchestrator for autonomous AI agents and applications.

`thinkdome` is a production-grade execution sandbox and tool engine designed for LLMs, agentic workflows, and safe code execution. It can be used directly as a **Python SDK** or as a **FastAPI server** with a suite of 24 tools with native privilege checks and type-safe schemas.


[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abeldirectory252/ThinkDome/blob/main/notebook/thinkdome_kaggle.ipynb)
[![Kaggle](https://kaggle.com/static/images/open-in-kaggle.svg)](https://kaggle.com/kernels/welcome?src=https://github.com/abeldirectory252/ThinkDome/blob/main/notebook/thinkdome_kaggle.ipynb)
---


## 🚀 Installation

You can install `thinkdome` directly from GitHub using `pip`:

```bash
pip install git+https://github.com/abeldirectory252/ThinkDome.git
```

---

## 🐍 Python SDK API (Simple Usage)

`thinkdome` provides a simple, clean, and powerful programmatic context manager for developers to safely execute code in an isolated environment.

### Basic Usage

```python
from thinkdome import Sandbox

# Run untrusted code in an ephemeral sandbox
with Sandbox() as dome:
    result = dome.run("print('Hello from inside ThinkDome')")
    
    print("Success:", result.success)
    print("Output:", result.output)  # stdout
    print("Errors:", result.error)   # stderr
    print("Exit Code:", result.exit_code)
```

### Advanced Usage & Resource Limits

You can easily configure resource limits, execution timeouts, and choose the underlying execution backend:

```python
from thinkdome import Sandbox

with Sandbox(
    language="python",       # Language to run
    timeout=30,              # Timeout limit in seconds
    memory_limit=256,        # Memory limit in MB
    network_allowed=False,   # Enable/disable internet access
    backend="auto",          # "auto" (uses docker if available, else subprocess), "docker", or "subprocess"
    workspace="./my_workspace" # Custom directory mapping for file sharing
) as dome:
    # Set up text files or binary media (like images/audio) before execution
    dome.write_file("data.csv", "name,value\nAlice,10\nBob,20\n")
    
    # You can write raw binary data directly (e.g. image inputs)
    image_bytes = b"..." # raw image bytes
    dome.write_file("input.png", image_bytes)
    
    # Run code that reads input files, processes them, and outputs new ones
    result = dome.run("""
import pandas as pd
df = pd.read_csv('data.csv')
print("Sum:", df['value'].sum())

# Modify the image or create a plot
with open("input.png", "rb") as f_in:
    data = f_in.read()
with open("output.png", "wb") as f_out:
    # process or save modified media
    f_out.write(data + b"_modified")
""")
    
    print("Stdout:", result.output.strip())
    
    # Read text or binary media files generated inside the sandbox workspace
    modified_image = dome.read_file_bytes("output.png")
    print("Modified image size:", len(modified_image))
    
    # List all files currently in the workspace
    files = dome.list_files()
    print("Workspace files:", files)
```

### Passing Media to `dome.run(..., files=...)`
Alternatively, you can pass binary media files directly when invoking `run()`:

```python
with open("photo.jpg", "rb") as f:
    photo_data = f.read()

with Sandbox() as dome:
    result = dome.run(
        code="print('Processed photo!')",
        files={"input_photo.jpg": photo_data}
    )
    # The output files can also be accessed from the result object:
    # result.files contains the binary contents of all files created during execution
    output_photo = result.files.get("output_photo.jpg")
```

---

## 🖥️ Command Line & API Server

`thinkdome` can also be run as a standalone API server that exposes the dynamic tool orchestrator and endpoints for remote agent clients.

### Start the API Server

```bash
# Start the FastAPI server on localhost:8000
thinkdome serve --host 127.0.0.1 --port 8000
```

### Run Code via CLI

```bash
thinkdome run "print('Executed via thinkdome CLI')"
```

---

## 🛡️ Six-Layer Security Containment

When running with the `docker` backend, execution is protected by a strict six-layer defense-in-depth security model:

```
                  [ Agent Egress / Squid Proxy ]
                                ▲
                                │  (Layer 6: Proxy-only Network)
   ┌───────────────────────────┴───────────────────────────┐
   │ Ephemeral Docker Container (Layer 1: OS Virtualization)│
   │                                                       │
   │  ┌─────────────────────────────────────────────────┐  │
   │  │   Sandbox User: UID 1000 (Layer 1: Non-root)     │  │
   │  └───────────────────────┬─────────────────────────┘  │
   │                          │                            │
   │  ┌───────────────────────▼─────────────────────────┐  │
   │  │   Read-Only rootfs (Layer 2: Filesystem Iso)    │  │
   │  └───────────────────────┬─────────────────────────┘  │
   │                          │                            │
   │  ┌───────────────────────▼─────────────────────────┐  │
   │  │   seccomp.json System Filters (Layer 3: Syscalls)│  │
   │  └───────────────────────┬─────────────────────────┘  │
   │                          │                            │
   │  ┌───────────────────────▼─────────────────────────┐  │
   │  │   cgroups limits (Layer 4: 0.5 CPU, 256MB RAM)  │  │
   │  └───────────────────────┬─────────────────────────┘  │
   │                          │                            │
   │  ┌───────────────────────▼─────────────────────────┐  │
   │  │   Drop ALL Kernel Capabilities (Layer 5: Caps)   │  │
   │  └─────────────────────────────────────────────────┘  │
   └───────────────────────────────────────────────────────┘
```

1. **OS-Level Virtualization**: Spawns ephemeral containers running under a non-root `sandbox` user (`UID 1000:1000`). Containers are destroyed immediately after execution.
2. **Filesystem Isolation**: The root filesystem is mounted as read-only (`read_only=True`). `/workspace` and `/tmp` are mounted as tiny `tmpfs` RAM-disks (64MB, `noexec`). No host paths are ever exposed.
3. **System Call Filtering**: Blocks dangerous system calls (e.g., `mount`, `umount2`, `reboot`, `ptrace`, `bpf`, `io_uring_*`) using a custom Docker seccomp profile (`security/seccomp.json`).
4. **Resource Constraints (cgroups v2)**: Limits execution to `0.5 CPU` cores, `256MB RAM` (with swap disabled), and a maximum of `20 PIDs` to prevent fork bombs. Supports dynamic OOM detection.
5. **Capability Dropping**: Drops all Linux kernel capabilities (`cap_drop=["ALL"]`).
6. **Network Egress Control**: Restricts egress traffic. Standard `LLM` queries have network disabled (`network_mode="none"`). `ADMIN` queries with network enabled are routed through a secure Squid proxy to allow HTTP/HTTPS auditing.

---

## 🐳 Docker Production Setup Guide (Windows & Linux)

To use the secure `docker` backend container isolation, `thinkdome` must communicate with a running Docker daemon.

### 🪟 1. Windows Setup (Docker Desktop)
Windows hosts utilize a named pipe (`\\.\pipe\docker_engine`) for daemon communication, which the Python `docker` client automatically resolves.

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Enable "Expose daemon on tcp://localhost:2375 without TLS" (optional, for remote debugging).
3. Ensure Docker Desktop is running.

### 🐧 2. Linux Setup
On Linux, the Docker daemon listens on `/var/run/docker.sock`.

1. Ensure your user has permissions to access the socket:
   ```bash
   sudo usermod -aG docker $USER
   ```
2. Log out and back in for the changes to take effect.

---

## 🤖 Connection with LLM Frameworks (LangChain/AutoGPT/CrewAI)

`thinkdome` exposes a dynamic tool schema that matches OpenAI/Anthropic/LangChain formats.
Get the active tools schema at:
```http
GET http://127.0.0.1:8000/orchestrator_schema.json
```
For API invocation examples and Kaggle deployment, check [thinkbox_kaggle.ipynb](file:///e:/Sandbox/Sandbox/thinkBox-main/thinkbox_kaggle.ipynb).
