#!/bin/sh
set -e

PORT="${PORT:-8000}"

echo "[entrypoint] Starting virtual display Xvfb on :99..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
sleep 1
export DISPLAY=:99

echo "[entrypoint] Virtual display started (DISPLAY=$DISPLAY). Launching Uvicorn on port $PORT..."
exec uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
