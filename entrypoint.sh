#!/bin/sh
set -e

PORT="${PORT:-8000}"

echo "[entrypoint] Cleaning any stale X11 locks..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

echo "[entrypoint] Starting virtual display Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
sleep 1
export DISPLAY=:99

echo "[entrypoint] Virtual display active (DISPLAY=$DISPLAY). Starting Uvicorn on port $PORT..."
exec uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
