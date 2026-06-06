#!/usr/bin/env bash
set -euo pipefail

echo "🧠 thinkdome starting..."

# Build executor image if it doesn't exist
if ! docker image inspect thinkdome-executor:latest >/dev/null 2>&1; then
    echo "📦 Building executor image..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # The executor Dockerfile is bundled at build time
    if [ -d "/opt/thinkdome/docker/executor" ]; then
        docker build -t thinkdome-executor:latest /opt/thinkdome/docker/executor
    else
        echo "⚠️  Executor Dockerfile not found. Build it manually:"
        echo "    docker build -t thinkdome-executor:latest docker/executor/"
    fi
fi

echo "🚀 Starting API server..."
exec thinkdome serve --host 0.0.0.0 --port 8000