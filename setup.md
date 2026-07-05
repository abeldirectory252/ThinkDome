# 🛠️ ThinkDome Production Sandbox: Ubuntu Setup Guide

This guide walks you through setting up and running the production-grade ThinkDome execution sandbox on **Ubuntu 22.04 / 24.04 LTS**.

It covers both the **Docker Compose (Recommended)** deployment and a **Native Systemd/Local** setup.

---

## 📋 Prerequisites & OS Setup

Update system packages and install basic utilities:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git python3-pip python3-venv build-essential
```

---

## 🐳 Option 1: Docker Compose Deployment (Recommended)

This is the easiest way to run the production-grade stack including the DinD (Docker-in-Docker) worker isolation layer, PostgreSQL, RabbitMQ, Redis, and OpenTelemetry.

### 1. Install Docker & Docker Compose
If not already installed, follow official Docker installation steps:
```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -dir /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker packages:
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 2. Configure Environment `.env`
Create a `.env` file in the root of the project:
```bash
cat <<EOF > .env
DATABASE_URL=postgresql://thinkdome:thinkdome@postgres:5432/thinkdome
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
REDIS_URL=redis://redis:6379/0
DOCKER_HOST=tcp://dind:2376
DOCKER_TLS_VERIFY=true
DOCKER_CERT_PATH=/certs/client
EXECUTOR_BACKEND=docker
EXECUTOR_IMAGE=thinkdome-executor:latest
FILE_STORAGE_DIR=/data/storage
POOL_ENABLED=true
POOL_MIN_WARM=3
POOL_MAX_SIZE=50
IDLE_TIMEOUT_SEC=600
EOF
```

### 3. Build the Executor Image
Build the sandbox container image that runs inside the isolated environments:
```bash
docker build -t thinkdome-executor:latest -f docker/executor/Dockerfile .
```

### 4. Start the Stack
Run the production Compose file:
```bash
docker compose -f docker/docker-compose.prod.yml up -d --build
```

### 5. Check Service Health
Ensure all components are running and healthy:
```bash
docker compose -f docker/docker-compose.prod.yml ps
```

---

## 💻 Option 2: Native Local Setup (No Docker-in-Docker)

Use this option to run services natively on the Ubuntu host. The API and Workers will talk to a local Docker socket and native state servers.

### 1. Install PostgreSQL, RabbitMQ, and Redis
```bash
# Install local packages
sudo apt install -y postgresql postgresql-contrib rabbitmq-server redis-server
```

### 2. Configure PostgreSQL Database
Log in as postgres user and set up database/user:
```bash
sudo -i -u postgres psql -c "CREATE USER thinkdome WITH PASSWORD 'thinkdome';"
sudo -i -u postgres psql -c "CREATE DATABASE thinkdome OWNER thinkdome;"
```

### 3. Setup Python Virtual Environment
Initialize virtual environment and install project dependencies:
```bash
# Create venv
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 4. Configure Local Environment `.env`
Create a `.env` file with local service addresses:
```bash
cat <<EOF > .env
DATABASE_URL=postgresql://thinkdome:thinkdome@localhost:5432/thinkdome
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
REDIS_URL=redis://localhost:6379/0
EXECUTOR_BACKEND=docker
DOCKER_HOST=unix:///var/run/docker.sock
DOCKER_TLS_VERIFY=false
FILE_STORAGE_DIR=./storage
POOL_ENABLED=true
POOL_MIN_WARM=3
POOL_MAX_SIZE=20
IDLE_TIMEOUT_SEC=600
EOF
```

### 5. Start Services

To run natively, start both the stateless API server and the RabbitMQ worker process:

#### Start the API Gateway:
```bash
source venv/bin/activate
uvicorn thinkdome.server:create_app --host 0.0.0.0 --port 8000 --factory
```

#### Start the Task Worker (in a separate terminal or service):
```bash
source venv/bin/activate
python3 -m thinkdome.services.task_worker
```

---

## ⚡ Verification & Testing

Verify that your sandbox orchestration works by sending a test code execution payload:

```bash
curl -X POST http://localhost:8000/v1/orchestrate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your_session_token>" \
  -d '{
    "id": "test_job_001",
    "type": "tool_use",
    "name": "run_code",
    "input": {
      "language": "python",
      "code": "import sys; print(f\"Python Version: {sys.version}\")"
    }
  }'
```

### Access Management & Monitoring Interfaces:
* **RabbitMQ Management Dashboard**: `http://localhost:15672` (default: `guest` / `guest`)
* **Prometheus Metrics Endpoint**: `http://localhost:8000/v1/metrics`
* **OTel Service Collector Pipeline**: Listens on Port `4317` (gRPC) and Port `4318` (HTTP)
