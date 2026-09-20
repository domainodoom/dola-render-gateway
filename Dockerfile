FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PORT=8000

EXPOSE 8000 8080

# Install ca-certificates, curl, xvfb, socat, and all standard Chromium shared libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xvfb \
    xauth \
    socat \
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

# Generate startup script with dual port support (8000 & 8080)
RUN printf '#!/bin/sh\nexport DISPLAY=:99\nXvfb :99 -screen 0 1280x720x24 -ac -noreset &\nsleep 1\nif [ "${PORT:-8000}" = "8000" ]; then\n  socat TCP-LISTEN:8080,fork,reuseaddr TCP:127.0.0.1:8000 &\nelif [ "${PORT:-8000}" = "8080" ]; then\n  socat TCP-LISTEN:8000,fork,reuseaddr TCP:127.0.0.1:8080 &\nfi\nexec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1\n' > /app/run.sh && chmod +x /app/run.sh

CMD ["/bin/sh", "/app/run.sh"]
