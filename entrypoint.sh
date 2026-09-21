#!/bin/sh
# Dola Render Gateway - Entrypoint
# Starts Xvfb virtual display, then launches Uvicorn.

cd /app

PORT="${PORT:-8080}"
DISPLAY_NUM=":99"

echo "[entrypoint] =========================================="
echo "[entrypoint] Dola Render Gateway starting on PORT: $PORT"
echo "[entrypoint] =========================================="

# --- 1. Clean stale X11 locks from previous crashes ---
echo "[entrypoint] Cleaning stale X11 locks..."
rm -f /tmp/.X99-lock /tmp/.X99-unix 2>/dev/null || true
rm -f /tmp/.X11-unix/X99 2>/dev/null || true
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# --- 2. Start Xvfb virtual framebuffer ---
if command -v Xvfb >/dev/null 2>&1; then
    echo "[entrypoint] Starting Xvfb on display ${DISPLAY_NUM}..."
    Xvfb ${DISPLAY_NUM} -screen 0 1280x720x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
    XVFB_PID=$!
    
    # Wait for Xvfb to be ready (poll up to 10 seconds)
    WAIT=0
    MAX_WAIT=10
    while [ $WAIT -lt $MAX_WAIT ]; do
        if xdpyinfo -display ${DISPLAY_NUM} >/dev/null 2>&1; then
            echo "[entrypoint] Xvfb is ready on display ${DISPLAY_NUM} (PID=$XVFB_PID)"
            break
        fi
        sleep 1
        WAIT=$((WAIT + 1))
    done
    
    if [ $WAIT -ge $MAX_WAIT ]; then
        echo "[entrypoint] WARNING: Xvfb did not start in time. Falling back to headless-only mode."
        echo "[entrypoint] Xvfb log:"
        cat /tmp/xvfb.log 2>/dev/null || true
        # Don't set DISPLAY so browser.py uses headless=new
    else
        export DISPLAY=${DISPLAY_NUM}
        echo "[entrypoint] DISPLAY=${DISPLAY} exported"
    fi
else
    echo "[entrypoint] Xvfb not found. Chromium will run in --headless=new mode."
fi

# --- 3. Sync system clock (helps with JWT issued-at-future errors) ---
if command -v ntpdate >/dev/null 2>&1; then
    echo "[entrypoint] Syncing system clock via ntpdate..."
    ntpdate -u pool.ntp.org 2>/dev/null || true
elif command -v chronyc >/dev/null 2>&1; then
    chronyc makestep 2>/dev/null || true
fi

# --- 4. Start Uvicorn ---
echo "[entrypoint] Starting Uvicorn on 0.0.0.0:${PORT}..."
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT}" --workers 1
