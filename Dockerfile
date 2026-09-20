FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Upgrade pip and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install chromium specifically for patchright
RUN patchright install chromium

COPY . .

# Railway routes traffic correctly when EXPOSE is omitted, but startCommand in railway.toml will use $PORT
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
