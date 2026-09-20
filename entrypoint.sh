#!/bin/sh
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
sleep 1
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
