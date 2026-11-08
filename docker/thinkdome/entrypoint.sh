#!/usr/bin/env bash
set -euo pipefail

echo "🧠 ThinkDome starting..."

# If command arguments are provided to the container, execute them directly
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "🚀 Starting API server..."
exec thinkdome serve --host 0.0.0.0 --port 8000