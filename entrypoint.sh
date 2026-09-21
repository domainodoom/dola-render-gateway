#!/bin/sh

cd /app

PORT="${PORT:-8080}"

echo "[entrypoint] Starting Dola Render Gateway on PORT: $PORT"

# Clean up stale X11 sockets/locks
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# Optional fallback Xvfb in background
if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1280x720x16 -noreset >/dev/null 2>&1 &
    export DISPLAY=:99
fi

echo "[entrypoint] Starting Uvicorn on 0.0.0.0:$PORT..."
exec python -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
