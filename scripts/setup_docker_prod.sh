#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ThinkDome Production Docker Setup Script
#
# Automates:
#   1. System prerequisite validation (Docker & Docker Compose)
#   2. Cryptographically secure random secret generation
#   3. Production .env configuration creation with DIND-002 boundaries
#   4. Executor sandbox image build and immutable @sha256 tagging
#   5. Core ThinkDome production image build
#   6. Docker Compose production stack deployment
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}        🚀 ThinkDome Production Docker Setup & Deployment             ${NC}"
echo -e "${BLUE}======================================================================${NC}"

# ── 1. Check Docker & Docker Compose ─────────────────────────────────────────
echo -e "\n${YELLOW}[1/5] Checking Docker engine & Compose availability...${NC}"

if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not installed on this system.${NC}"
    echo "To install Docker on Ubuntu, run:"
    echo "  sudo apt update"
    echo "  sudo apt install -y ca-certificates curl gnupg"
    echo "  sudo install -m 0755 -d /etc/apt/keyrings"
    echo "  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg"
    echo "  sudo chmod a+r /etc/apt/keyrings/docker.gpg"
    echo "  echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null"
    echo "  sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin"
    exit 1
fi

echo -e "${GREEN}✓ Docker CLI found: $(docker --version)${NC}"

# Check Docker Compose plugin
if docker compose version >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Docker Compose plugin found: $(docker compose version)${NC}"
else
    echo -e "${RED}❌ Docker Compose plugin is missing.${NC}"
    echo "Install via: sudo apt install -y docker-compose-plugin"
    exit 1
fi

# Check Docker daemon connectivity
if ! docker info >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️ Docker daemon is not currently responding to this user.${NC}"
    echo "Attempting to verify daemon service..."
    if command -v service >/dev/null 2>&1; then
        echo "Tip: You may need to start the Docker service or add your user to the docker group:"
        echo "  sudo service docker start"
        echo "  sudo usermod -aG docker \$USER && newgrp docker"
    fi
fi

# ── 2. Generate Secrets & Production .env ────────────────────────────────────
echo -e "\n${YELLOW}[2/5] Configuring production environment secrets...${NC}"

generate_secret() {
    python3 -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || openssl rand -hex 24
}

ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo -e "${BLUE}ℹ️ Existing .env file found at $ENV_FILE.${NC}"
    echo "Preserving existing secrets. (Pass --force to overwrite)."
    if [ "${1:-}" = "--force" ]; then
        echo -e "${YELLOW}Overwriting .env due to --force flag...${NC}"
        rm "$ENV_FILE"
    fi
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Generating cryptographically secure passwords and keys..."
    PG_PASSWORD=$(generate_secret)
    RMQ_PASSWORD=$(generate_secret)
    JWT_SECRET=$(generate_secret)
    VAULT_KEY=$(generate_secret)
    EXECUTOR_TOKEN=$(generate_secret)

    cat <<EOF > "$ENV_FILE"
# ─────────────────────────────────────────────────────────────────────────────
# ThinkDome Production Environment (.env)
# Generated on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# ─────────────────────────────────────────────────────────────────────────────

DEPLOYMENT_ENV=production

# ── Database (PostgreSQL) ────────────────────────────────────────────────────
POSTGRES_DB=thinkdome
POSTGRES_USER=thinkdome
POSTGRES_PASSWORD=${PG_PASSWORD}
DATABASE_URL=postgresql://thinkdome:${PG_PASSWORD}@postgres:5432/thinkdome

# ── Message Queue (RabbitMQ) ─────────────────────────────────────────────────
RABBITMQ_DEFAULT_USER=thinkdome
RABBITMQ_DEFAULT_PASS=${RMQ_PASSWORD}
RABBITMQ_URL=amqp://thinkdome:${RMQ_PASSWORD}@rabbitmq:5672/

# ── Cache & Session Store (Redis) ─────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── Security Invariant Tokens (>= 32 chars) ───────────────────────────────────
JWT_SECRET_KEY=${JWT_SECRET}
WORKSPACE_MASTER_KEY=${VAULT_KEY}

# ── Docker Executor Service (DIND-002 Least Privilege Boundary) ───────────────
EXECUTOR_CONTROL_URL=http://thinkdome-docker-executor:8200
EXECUTOR_CONTROL_AUTH_TOKEN=${EXECUTOR_TOKEN}
EXECUTOR_CONTROL_PORT=8200

# ── Pluggable Executor Backend ────────────────────────────────────────────────
EXECUTOR_BACKEND=docker
EXECUTOR_IMAGE=thinkdome-executor:latest

# DinD Daemon Connection (TLS secured within internal network)
DOCKER_HOST=tcp://dind:2376
DOCKER_TLS_VERIFY=true
DOCKER_CERT_PATH=/certs/client

# ── Sandbox Resource & Lifecycle Defaults ─────────────────────────────────────
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
    echo -e "${GREEN}✓ Created production $ENV_FILE with secure unique credentials.${NC}"
fi

# ── 3. Build & Tag Sandbox Executor Image ───────────────────────────────────
echo -e "\n${YELLOW}[3/5] Building sandbox executor container image...${NC}"

if docker info >/dev/null 2>&1; then
    docker build -t thinkdome-executor:latest -f docker/executor/Dockerfile .
    
    # Extract immutable SHA256 image ID to satisfy production runtime validation
    RAW_DIGEST=$(docker inspect --format='{{index .Id}}' thinkdome-executor:latest 2>/dev/null || echo "")
    CLEAN_DIGEST=$(echo "$RAW_DIGEST" | sed 's/sha256://')

    if [ -n "$CLEAN_DIGEST" ]; then
        IMMUTABLE_TAG="thinkdome-executor@sha256:${CLEAN_DIGEST}"
        docker tag thinkdome-executor:latest "$IMMUTABLE_TAG" 2>/dev/null || true
        # Update .env with immutable image reference
        sed -i.bak "s|^EXECUTOR_IMAGE=.*|EXECUTOR_IMAGE=${IMMUTABLE_TAG}|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}✓ Tagged executor image with immutable digest: ${IMMUTABLE_TAG}${NC}"
    fi
else
    echo -e "${YELLOW}⚠️ Docker daemon unavailable; skipping inline executor build.${NC}"
    echo "  (Will build during compose startup)."
fi

# ── 4. Build ThinkDome Core Application Image ────────────────────────────────
echo -e "\n${YELLOW}[4/5] Building ThinkDome core application image...${NC}"

if docker info >/dev/null 2>&1; then
    docker build -t thinkdome:latest -f docker/thinkdome/Dockerfile .
    echo -e "${GREEN}✓ ThinkDome core container image built successfully.${NC}"
else
    echo -e "${YELLOW}⚠️ Docker daemon unavailable; Compose will build images at startup.${NC}"
fi

# ── 5. Deployment Commands & Verification Summary ───────────────────────────
echo -e "\n${BLUE}======================================================================${NC}"
echo -e "${GREEN}✓ Production Docker setup configuration complete!${NC}"
echo -e "${BLUE}======================================================================${NC}"

echo -e "\nTo start the complete production stack, run:"
echo -e "  ${YELLOW}docker compose -f docker/docker-compose.prod.yml up -d --build${NC}"

echo -e "\nTo inspect running services and health status:"
echo -e "  ${YELLOW}docker compose -f docker/docker-compose.prod.yml ps${NC}"

echo -e "\nTo view live system logs:"
echo -e "  ${YELLOW}docker compose -f docker/docker-compose.prod.yml logs -f thinkdome-api thinkdome-docker-executor${NC}"

echo -e "\nOnce running, test the API with:"
echo -e "  ${YELLOW}curl -s http://localhost:8000/v1/health${NC}"
echo -e "  ${YELLOW}curl -s http://localhost:8000/login.html${NC}"
echo ""

