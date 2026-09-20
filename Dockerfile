FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Upgrade pip and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install chromium specifically for patchright
RUN patchright install chromium

COPY . .

# Expose the port Railway expects
EXPOSE 8000

# Start the uvicorn server
CMD sh -c "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"
