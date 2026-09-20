FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8000

# Install tini, xvfb, xauth, ffmpeg, fonts, curl, ca-certificates, and all Chromium dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    curl \
    ca-certificates \
    xvfb \
    xauth \
    ffmpeg \
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

# Install Chromium
RUN patchright install chromium

COPY . .

# Ensure storage directories exist
RUN mkdir -p /data/accounts /data/downloads accounts downloads

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1280x720x24", "python", "server.py"]
