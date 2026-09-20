FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# Install xvfb, xauth, and graphics utilities for virtual display
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install chromium for patchright
RUN patchright install chromium

COPY . .

# Run uvicorn inside xvfb virtual display using dynamic Railway $PORT
CMD ["sh", "-c", "xvfb-run -a -s '-screen 0 1280x720x24' python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
