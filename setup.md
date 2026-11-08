# 🛠️ ThinkDome Production Sandbox: Ubuntu Setup Guide

This guide walks you through setting up and running the production-grade ThinkDome execution sandbox on **Ubuntu 22.04 / 24.04 LTS**.

It covers the **Production Docker Compose Deployment (Recommended)**, the **Fast-Track Automated Script**, and a **Native Local / Development** alternative.

---

## 📋 Prerequisites & OS Setup

Update system packages and install prerequisites:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git python3-pip python3-venv build-essential openssl
```

---

## 🐳 Option 1: Docker Compose Production Deployment (Recommended)

This runs the complete, production-hardened microservice stack:
* **`thinkdome-api`**: Public FastAPI web service & Web UI (Port `8000`).
* **`thinkdome-docker-executor`**: Dedicated control-plane service (Port `8200`, DIND-002 boundary).
* **`thinkdome-worker`**: Distributed asynchronous task execution consumer.
* **`dind`**: Hardened Docker-in-Docker isolation daemon with automated TLS certificates.
* **`postgres`**: State store for users, RBAC roles, and sandboxes (Port `5432`).
* **`rabbitmq`**: Task distribution message broker (Port `5672`, Management UI `15672`).
* **`redis`**: Session caching and rate limiting (Port `6379`).
* **`otel-collector`**: OpenTelemetry distributed metrics and trace collector.

---

### Method A: Fast-Track Automated Setup (1 Command)

We provide an automated setup script that installs prerequisites, generates cryptographically strong passwords, builds the executor with an immutable `@sha256:` tag, and writes `.env`:

```bash
# 1. Run the automated production setup script:
./scripts/setup_docker_prod.sh

# 2. Launch the stack:
docker compose -f docker/docker-compose.prod.yml up -d --build

# 3. Check container status:
docker compose -f docker/docker-compose.prod.yml ps
```

---

### Method B: Manual Step-by-Step Production Setup

If you prefer to configure each step manually:

#### 1. Install Docker Engine & Compose Plugin
```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker packages:
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker:
sudo systemctl enable --now docker || sudo service docker start

# Grant non-root user access (avoids sudo requirement):
sudo usermod -aG docker $USER
newgrp docker
```

#### 2. Generate Production Secrets & `.env`
ThinkDome production runtime validation enforces strict security invariants:
* Passwords for Postgres and RabbitMQ must **never** use default credentials.
* `JWT_SECRET_KEY`, `WORKSPACE_MASTER_KEY`, and `EXECUTOR_CONTROL_AUTH_TOKEN` must each be at least **32 characters**.
* Public API and Worker services do **not** mount Docker sockets or Docker TLS certs (DIND-002 boundary).

Generate secrets using `python3` or `openssl`:
```bash
PG_PASS=$(openssl rand -hex 24)
RMQ_PASS=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
VAULT_KEY=$(openssl rand -hex 32)
EXEC_TOKEN=$(openssl rand -hex 32)

cat <<EOF > .env
DEPLOYMENT_ENV=production

# ── Database (PostgreSQL) ────────────────────────────────────────────────────
POSTGRES_DB=thinkdome
POSTGRES_USER=thinkdome
POSTGRES_PASSWORD=${PG_PASS}
DATABASE_URL=postgresql://thinkdome:${PG_PASS}@postgres:5432/thinkdome

# ── Message Queue (RabbitMQ) ─────────────────────────────────────────────────
RABBITMQ_DEFAULT_USER=thinkdome
RABBITMQ_DEFAULT_PASS=${RMQ_PASS}
RABBITMQ_URL=amqp://thinkdome:${RMQ_PASS}@rabbitmq:5672/

# ── Cache & Session Store (Redis) ─────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── Cryptographic Secrets (>= 32 chars) ───────────────────────────────────────
JWT_SECRET_KEY=${JWT_SECRET}
WORKSPACE_MASTER_KEY=${VAULT_KEY}

# ── Docker Executor Service (DIND-002 Boundary) ───────────────────────────────
EXECUTOR_CONTROL_URL=http://thinkdome-docker-executor:8200
EXECUTOR_CONTROL_AUTH_TOKEN=${EXEC_TOKEN}
EXECUTOR_CONTROL_PORT=8200

# ── Pluggable Container Backend ───────────────────────────────────────────────
EXECUTOR_BACKEND=docker
EXECUTOR_IMAGE=thinkdome-executor:latest

# DinD Daemon TLS (internal Docker network)
DOCKER_HOST=tcp://dind:2376
DOCKER_TLS_VERIFY=true
DOCKER_CERT_PATH=/certs/client

# ── Resource Limits & Defaults ────────────────────────────────────────────────
FILE_STORAGE_DIR=/data/storage
POOL_ENABLED=true
POOL_MIN_WARM=3
POOL_MAX_SIZE=50
IDLE_TIMEOUT_SEC=180
MAX_EXEC_TIMEOUT_MS=30000
CPU_TIME_LIMIT_SEC=10
MEMORY_LIMIT_MB=256

# ── Observability ─────────────────────────────────────────────────────────────
OTEL_ENABLED=false
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=thinkdome
EOF
```

#### 3. Build Sandbox Executor Image (`thinkdome-executor:latest`)
All containerized execution in ThinkDome (such as running Python code or terminal commands like `ping`, `curl`, and `pip install`) runs inside the `thinkdome-executor` sandbox container image.

##### Fast Build (Development & Local Docker):
```bash
# Build the executor image from the repository root:
docker build -t thinkdome-executor:latest docker/executor/

# Or run the included build script:
./docker/executor/build.sh
```
*(If your user does not have direct Docker socket access, prefix with `sudo` or add your user to the `docker` group).*

##### Production Build (with Immutable `@sha256:` Digest):
In production, ThinkDome runtime security enforces immutable digest references:
```bash
# 1. Build base executor sandbox image:
docker build -t thinkdome-executor:latest docker/executor/

# 2. Extract immutable SHA256 digest:
DIGEST=$(docker inspect --format='{{index .Id}}' thinkdome-executor:latest | sed 's/sha256://')
IMMUTABLE_TAG="thinkdome-executor@sha256:${DIGEST}"
docker tag thinkdome-executor:latest "$IMMUTABLE_TAG"

# 3. Update EXECUTOR_IMAGE in .env:
sed -i "s|^EXECUTOR_IMAGE=.*|EXECUTOR_IMAGE=${IMMUTABLE_TAG}|" .env
echo "✓ Pinned EXECUTOR_IMAGE to ${IMMUTABLE_TAG}"
```

> [!NOTE]
> **What the Executor Image Contains:**
> - Base: `python:3.10-slim`
> - CLI & Networking utilities: `iputils-ping`, `net-tools`, `iproute2`, `curl`, `procps`
> - Pre-warmed Python libraries: `numpy`, `pandas`, `requests`, `matplotlib`, `scipy`, `pydantic`, `httpx`
> - Least-privilege isolation: runs as non-root `sandbox` user (`uid: 1000`) in `/workspace`.

#### 4. Configure Docker Egress Network & Proxy

ThinkDome enforces **network isolation** for all sandbox containers. Instead of allowing sandboxes to access the internet directly, all outbound traffic is routed through a Squid forward-proxy on a Docker-internal network. This architecture prevents arbitrary egress while still allowing whitelisted API calls (e.g., to PyPI, OpenAI, Anthropic).

> [!IMPORTANT]
> This step is **required** before sandbox execution will work. Without the egress network, any execution request with `allow_network: true` will fail with:
> ```
> NetworkIsolationError: Approved egress network 'thinkbox-egress' is unavailable
> ```

##### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  Docker Host                                                    │
│                                                                 │
│  ┌──────────────┐     thinkbox-egress      ┌────────────────┐  │
│  │   Sandbox     │ ──── (internal, no  ──── │ thinkbox-proxy │  │
│  │  Container    │      direct internet)    │   (Squid)      │  │
│  └──────────────┘                           └───────┬────────┘  │
│                                                     │           │
│                                           thinkbox-upstream     │
│                                             (bridge, has        │
│                                              internet)          │
│                                                     │           │
└─────────────────────────────────────────────────────┼───────────┘
                                                      │
                                              ┌───────▼────────┐
                                              │   Internet     │
                                              │  (whitelisted  │
                                              │   domains only)│
                                              └────────────────┘
```

- **`thinkbox-egress`**: A Docker-internal bridge network (no direct internet). Sandbox containers and the proxy both attach here.
- **`thinkbox-upstream`**: A standard bridge network with internet access. Only the proxy container connects to this.
- **`thinkbox-proxy`**: A hardened Squid proxy that forwards traffic only to whitelisted domains defined in `docker/proxy/squid.conf`.

##### If Using Docker Compose (Automatic)

If you're deploying via `docker compose` (Step 5 below), both networks and the proxy are created automatically — **no manual action is needed**. Skip to Step 5.

##### If Running ThinkDome Locally (Against Host Docker)

When running ThinkDome directly on the host (e.g., `python think serve`) using the local Docker socket, you must create the egress network and proxy manually:

**Step 1: Create the Docker Networks**
```bash
# Create the internal egress network (sandboxes connect here)
docker network create \
  --driver bridge \
  --internal \
  --label thinkdome.network=egress-proxy \
  thinkbox-egress

# Create the upstream network (proxy uses this for internet access)
docker network create \
  --driver bridge \
  thinkbox-upstream
```

> [!WARNING]
> The `thinkbox-egress` network **must** satisfy all of the following or the sandbox policy will reject it:
> - Driver: `bridge`
> - Internal: `true` (the `--internal` flag)
> - Label: `thinkdome.network=egress-proxy`

**Step 2: Start the Squid Egress Proxy**
```bash
docker run -d \
  --name thinkbox-proxy \
  --read-only \
  --cap-drop ALL \
  --cap-add SETUID \
  --cap-add SETGID \
  --security-opt no-new-privileges:true \
  --tmpfs /var/run/squid \
  --tmpfs /var/spool/squid \
  --tmpfs /var/log/squid \
  -v "$(pwd)/docker/proxy/squid.conf:/etc/squid/squid.conf:ro" \
  --restart unless-stopped \
  ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029
```

**Step 3: Attach the Proxy to Both Networks**
```bash
# Connect proxy to the internal egress network (sandbox-facing side)
docker network connect --alias thinkbox-proxy thinkbox-egress thinkbox-proxy

# Connect proxy to the upstream network (internet-facing side)
docker network connect thinkbox-upstream thinkbox-proxy
```

**Step 4: Verify the Setup**
```bash
# Confirm both networks exist with correct configuration
docker network inspect thinkbox-egress --format '{{.Driver}} internal={{.Internal}} label={{index .Labels "thinkdome.network"}}'
# Expected: bridge internal=true label=egress-proxy

# Confirm the proxy container is running and connected
docker inspect thinkbox-proxy --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
# Expected output should include: thinkbox-egress thinkbox-upstream

# Test proxy connectivity from inside the egress network
docker run --rm --network thinkbox-egress curlimages/curl \
  -x http://thinkbox-proxy:3128 -s -o /dev/null -w "%{http_code}" https://pypi.org
# Expected: 200
```

##### Customizing Allowed Domains

The proxy whitelist is configured in [`docker/proxy/squid.conf`](docker/proxy/squid.conf). By default, the following domains are allowed:

| Domain | Purpose |
|---|---|
| `.anthropic.com` | Anthropic / Claude API |
| `.openai.com` | OpenAI API |
| `.googleapis.com` | Google Cloud / Gemini API |
| `.huggingface.co` | Hugging Face models & datasets |
| `.pypi.org` | Python package index |
| `.pythonhosted.org` | Python package downloads |
| `.duckduckgo.com` | Web search |

To add domains, edit `docker/proxy/squid.conf` and add a new ACL line:
```
acl allowed_domains dstdomain .example.com
```
Then reload the proxy configuration:
```bash
docker exec thinkbox-proxy squid -k reconfigure
```

##### Cleanup (Tear Down Egress Network)

To remove the egress network and proxy when no longer needed:
```bash
docker rm -f thinkbox-proxy
docker network rm thinkbox-egress thinkbox-upstream
```

#### 5. Build Core ThinkDome Container Image
```bash
docker build -t thinkdome:latest -f docker/thinkdome/Dockerfile .
```

#### 6. Start the Production Stack
```bash
docker compose -f docker/docker-compose.prod.yml up -d --build
```

#### 7. Verify Service Health
```bash
docker compose -f docker/docker-compose.prod.yml ps
```
All core services (`postgres`, `rabbitmq`, `redis`, `dind`, `thinkdome-docker-executor`, `thinkdome-api`, `thinkdome-worker`) should report `healthy` or `running`.

---

## ⚡ Verification & Testing

### 1. Test Gateway Health
```bash
curl -s http://localhost:8000/v1/health | jq .
```
Expected output:
```json
{
  "status": "healthy",
  "version": "0.2.0"
}
```

### 2. User Authentication (Login)
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}'
```
Save the returned token: `TOKEN="<access_token>"`

### 3. Create a User Sandbox
```bash
curl -X POST http://localhost:8000/v1/sandboxes \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Production Analytics Sandbox",
    "memory_mb": 512,
    "cpu_cores": 2.0,
    "timeout_sec": 60,
    "is_long_lived": false
  }'
```

### 4. Execute Code in Sandbox Stream (SSE)
```bash
curl -N -X POST http://localhost:8000/v1/execute/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "language": "python",
    "code": "import sys, platform; print(f\"Python: {sys.version.split()[0]} on {platform.system()}\")"
  }'
```

---

## 💻 Option 2: Native Local Setup (No Docker Required)

If your host does not have Docker or you are developing locally:

```bash
# 1. Setup virtual environment:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .

# 2. Configure environment with subprocess backend:
cat <<EOF > .env
DEPLOYMENT_ENV=development
EXECUTOR_BACKEND=subprocess
EXECUTOR_BACKEND_USE_FALLBACK=true
FILE_STORAGE_DIR=./storage
EOF

# 3. Start API server:
python think serve --host 0.0.0.0 --port 8000
```

---

## 🛡️ Production Security Architecture Reference

* **DIND-002 Least-Privilege Boundary**: Public API workers never talk to Docker sockets directly. They talk to `thinkdome-docker-executor:8200` with HMAC token verification.
* **Network Egress Filtering**: Isolated containers route all outbound traffic through the egress proxy (`thinkbox-proxy`). Direct internet egress is blocked by default.
* **Auto-Deactivation & Short-Life Policy**: Sandboxes default to short lifetimes (minutes) and automatically deactivate after task completion unless explicitly requested as persistent (`is_long_lived: true`).
* **Multi-User Isolation**: Every sandbox belongs to its authenticated user (`owner`). Users cannot see or run code in other users' environments.
* **Log Inspection**:
  ```bash
  # View API logs:
  docker compose -f docker/docker-compose.prod.yml logs -f thinkdome-api

  # View Docker Executor control logs:
  docker compose -f docker/docker-compose.prod.yml logs -f thinkdome-docker-executor

  # View Background Worker logs:
  docker compose -f docker/docker-compose.prod.yml logs -f thinkdome-worker
  ```

---

## 🔍 Troubleshooting Docker & Executor Issues

### 1. `Executor image 'thinkdome-executor:latest' not found`
If terminal commands (like `ping 8.8.8.8`, `python script.py`, `pip install`) display:
```
⚠️ Executor unavailable: Executor image 'thinkdome-executor:latest' not found and cannot build.
```
**Fix**: Build the executor sandbox image on the host Docker daemon:
```bash
docker build -t thinkdome-executor:latest docker/executor/
```
Or run the build script directly:
```bash
./docker/executor/build.sh
```

### 2. `Docker socket permission denied: PermissionError(13, 'Permission denied')`
If ThinkDome cannot communicate with `/var/run/docker.sock`:
**Fix**: Add your Linux user to the `docker` group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```
Verify access by running:
```bash
docker ps
```
Once this succeeds without `sudo`, restart the ThinkDome server:
```bash
python think serve --port 8000
```

### 3. `NetworkIsolationError: Approved egress network 'thinkbox-egress' is unavailable`

If sandbox execution fails with:
```
thinkdome.sandbox.network.docker_policy.NetworkIsolationError: Approved egress network 'thinkbox-egress' is unavailable
```
This means the Docker egress network required for sandbox network isolation has not been created. This typically happens when running ThinkDome locally against the host Docker daemon instead of through Docker Compose (which creates it automatically).

**Fix**: Create the egress network, upstream network, and proxy container as described in **Step 4: Configure Docker Egress Network & Proxy** above.

Quick one-liner to create just the network (sandbox network access will work but egress will fail without the proxy):
```bash
docker network create --driver bridge --internal --label thinkdome.network=egress-proxy thinkbox-egress
```

Other related `NetworkIsolationError` variants and their causes:

| Error Message | Cause |
|---|---|
| `Approved egress network must use the bridge driver` | Network was created with a non-bridge driver (e.g., `overlay`). Recreate with `--driver bridge`. |
| `Approved egress network must be Docker-internal` | Network was created without the `--internal` flag. Recreate with `--internal`. |
| `Approved egress network is missing the required security label` | Network is missing the label `thinkdome.network=egress-proxy`. Recreate with `--label thinkdome.network=egress-proxy`. |
| `Approved egress network has an ambiguous identity` | Multiple Docker networks named `thinkbox-egress` exist. Remove duplicates with `docker network rm`. |
