#!/bin/sh
set -e

cd /app

PORT="${PORT:-8080}"

echo "[entrypoint] Working directory: $(pwd)"
echo "[entrypoint] Target PORT: $PORT"

if command -v xvfb-run >/dev/null 2>&1; then
    echo "[entrypoint] Running via xvfb-run..."
    exec xvfb-run -a -s "-screen 0 1280x720x16" python -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
else
    echo "[entrypoint] Starting virtual display Xvfb manually..."
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
    Xvfb :99 -screen 0 1280x720x16 -ac -nolisten tcp +extension GLX +render -noreset &
    sleep 2
    export DISPLAY=:99
    exec python -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
fi
