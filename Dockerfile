FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Upgrade pip and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install chromium specifically for patchright
RUN patchright install chromium

COPY . .

# Tell Railway to proxy traffic to port 8000
EXPOSE 8000

# Run uvicorn on dynamic Railway PORT (or 8000 fallback)
CMD python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
