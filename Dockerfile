FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# Install xvfb and xauth for virtual display
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

RUN chmod +x entrypoint.sh

CMD ["/bin/sh", "entrypoint.sh"]
