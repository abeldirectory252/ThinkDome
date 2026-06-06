#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build -t thinkdome-executor:latest "$SCRIPT_DIR"
echo "✅ thinkdome-executor:latest built successfully"