FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99

# Install ca-certificates, curl, xvfb, and all standard Chromium shared libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xvfb \
    xauth \
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
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Chromium
RUN patchright install chromium

COPY . .

# Generate bulletproof startup script inside Linux container
RUN printf '#!/bin/sh\nexport DISPLAY=:99\nXvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &\nsleep 1\nexec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1\n' > /app/run.sh && chmod +x /app/run.sh

CMD ["/bin/sh", "/app/run.sh"]
