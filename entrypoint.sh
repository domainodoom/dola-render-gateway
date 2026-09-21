#!/bin/sh
# Dola Render Gateway - Entrypoint
# Minimal, crash-proof startup for Railway free tier

set -e
cd /app

PORT="${PORT:-8080}"

echo "[entrypoint] === Dola Render Gateway ==="
echo "[entrypoint] PORT=$PORT"
echo "[entrypoint] Python: $(python --version 2>&1)"
echo "[entrypoint] RAM: $(cat /proc/meminfo 2>/dev/null | grep MemAvailable | awk '{print $2, $3}' || echo 'unknown')"

# Clean stale X11 lock files from previous container runs
rm -f /tmp/.X99-lock 2>/dev/null || true
rm -f /tmp/.X11-unix/X99 2>/dev/null || true
mkdir -p /tmp/.X11-unix 2>/dev/null || true
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# Try to start Xvfb (virtual display for extension support)
# If it fails, browser.py will fall back to --headless=new automatically
if command -v Xvfb >/dev/null 2>&1; then
    echo "[entrypoint] Starting Xvfb :99..."
    Xvfb :99 -screen 0 1280x720x24 -ac >/tmp/xvfb.log 2>&1 &
    sleep 3
    if kill -0 $! 2>/dev/null; then
        export DISPLAY=:99
        echo "[entrypoint] Xvfb OK, DISPLAY=:99"
    else
        echo "[entrypoint] Xvfb failed to stay running - using headless mode"
        echo "[entrypoint] Xvfb log: $(cat /tmp/xvfb.log 2>/dev/null)"
        unset DISPLAY
    fi
else
    echo "[entrypoint] Xvfb not found - using headless mode"
fi

# Try NTP sync (optional, fixes JWT clock issues)
if command -v ntpdate >/dev/null 2>&1; then
    ntpdate -u pool.ntp.org 2>/dev/null || true
    echo "[entrypoint] Clock synced"
fi

echo "[entrypoint] Starting Uvicorn on 0.0.0.0:${PORT}..."
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT}" --workers 1 --timeout-keep-alive 75
