FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install ca-certificates, curl, and Xvfb virtual display
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Chromium and all OS system dependencies automatically
RUN patchright install --with-deps chromium

COPY . .

RUN chmod +x entrypoint.sh

CMD ["/bin/sh", "entrypoint.sh"]
