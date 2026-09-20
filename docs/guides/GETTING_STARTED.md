# ThinkDome — Getting Started Guide

> Complete onboarding and operations guide for developers, AI engineers, and platform administrators.

---

## 1. Prerequisites

Before running ThinkDome, ensure the following software is installed on your host machine:

- **Python**: 3.9, 3.10, 3.11, or 3.12
- **Docker Engine**: Required for container-based isolation (`docker` CLI and daemon active)
- **Redis** *(optional)*: For cached listing, distributed session storage, and LangGraph checkpointing
- **Hardware Virtualization (KVM)** *(optional)*: Required only if using Firecracker MicroVM or Kata Containers

---

## 2. Installation

### 2.1 From GitHub (Standard)

```bash
pip install git+https://github.com/abeldirectory252/ThinkDome.git
```

### 2.2 For Development & Customization

```bash
git clone https://github.com/abeldirectory252/ThinkDome.git
cd ThinkDome

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install with development dependencies
pip install -e .
```

---

## 3. Verify Environment

Run the automated diagnostic check to inspect hypervisor capabilities, Docker availability, and system boundaries:

```bash
thinkdome check
```

Example output:
```text
[✓] Python Runtime: 3.11.8
[✓] Subprocess backend: AVAILABLE
[✓] Docker backend: AVAILABLE (Docker version 24.0.5)
[✓] Seccomp support: ENABLED
[✓] Storage directory: /home/sandbox/ThinkDome/storage (OK)
[!] KVM / MicroVM: NOT AVAILABLE (Hardware virtualization disabled)
```

---

## 4. Basic CLI Usage

ThinkDome provides dual command aliases: `thinkdome` and `think`.

### 4.1 Ephemeral Execution

Run arbitrary Python code directly inside an isolated sandbox:

```bash
# Run with subprocess backend (lightweight development mode)
thinkdome run 'print(2 ** 64)' --backend subprocess

# Run inside locked-down Docker container
thinkdome run 'import sys; print(sys.version)' --backend docker
```

### 4.2 Restricting Resources & Network Egress

```bash
# Run with 256MB RAM limit and 10 second timeout
thinkdome run 'import time; time.sleep(1)' --memory 256M --timeout 10

# Run with explicit domain allowlisting (default denies all other outbound traffic)
thinkdome run 'import urllib.request; print(urllib.request.urlopen("https://api.github.com").getcode())' \
  --allow-domain api.github.com
```

---

## 5. Web Dashboard & API Server

### 5.1 Starting the Server

To launch the FastAPI HTTP/WebSocket server and web dashboard:

```bash
think serve --host 0.0.0.0 --port 8000
```

Once running, navigate to:
- **Web Dashboard**: `http://localhost:8000`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **ReDoc API**: `http://localhost:8000/redoc`

### 5.2 Default Credentials

During initial database seeding, the default administrator credentials are:
- **Username**: `admin`
- **Password**: Configured in environment or seeded via `python -m thinkdome.security.auth.seed`

---

## 6. Multi-Tenant Architecture & Database Migrations

ThinkDome uses an isolated per-tenant database model.

### 6.1 Database Migrations

```bash
# Run database schema migrations for all active sites
think migrate

# Generate a new migration after updating ORM models
think makemigrations "add_new_feature_fields"
```

### 6.2 Managing Sites & Workspaces

```bash
# Create a new tenant site
think site create --domain tenant1.domain.internal

# List registered tenant sites
think site list
```

---

## 7. Working with FileBox

FileBox provides each sandbox with a scoped, safe virtual filesystem:

```bash
# Upload a file to FileBox
think filebox put local_data.csv /data/local_data.csv

# List files in virtual sandbox storage
think filebox ls /data

# Download a processed artifact
think filebox get /data/results.json ./results.json
```

---

## 8. Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `Docker daemon connection failed` | Docker service is not running | Run `sudo systemctl start docker` |
| `Memory limit exceeded` | Process exceeded allocated RAM | Increase `--memory` parameter (e.g. `--memory 1024M`) |
| `Network egress blocked` | Default-deny policy triggered | Add destination to `--allow-domain` |
| `Permission denied on /dev/kvm` | User not in `kvm` group | Run `sudo usermod -aG kvm $USER` |
