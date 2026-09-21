FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8080 \
    DISPLAY=:99

# Install system dependencies:
# - tini: PID 1 process manager (handles signals correctly)
# - xvfb, xauth, x11-utils: Virtual X11 display (required for Chromium with extensions)
# - xdpyinfo: used by entrypoint.sh to poll Xvfb readiness
# - ffmpeg: video processing
# - ntpdate: NTP clock sync (fixes JWT issued-at-future errors)
# - fonts, ca-certificates, curl: utilities
# - All Chromium shared library dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    curl \
    ca-certificates \
    xvfb \
    xauth \
    x11-utils \
    ffmpeg \
    ntpdate \
    fonts-liberation \
    fonts-noto-color-emoji \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Chromium browser for patchright
RUN patchright install chromium

COPY . .

# Ensure storage directories exist and entrypoint is executable
RUN mkdir -p /data/accounts /data/downloads accounts downloads && \
    chmod +x entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/entrypoint.sh"]
