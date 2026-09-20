#!/bin/sh
set -e

cd /app

PORT="$"{PORT:-8080}"

echo "[entrypoint] Working directory: $"(pwd)"
echo "[entrypoint] Target PORT: $"PORT"

exec xvfb-run -a -s "-screen 0 1280x720x24" python -m uvicorn server:app --host 0.0.0.0 --port "$"PORT" --workers 1
