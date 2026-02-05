# Stage 1: Base image with all heavy dependencies (built once, cached)
FROM python:3.14-slim AS base

# Install system dependencies including Playwright browser dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    git \
    libreoffice-writer \
    libreoffice-calc \
    chromium \
    chromium-driver \
    # Playwright dependencies for headless browser testing
    fonts-liberation \
    fonts-noto-color-emoji \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install all Python dependencies (the expensive part)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ui/backend/requirements.txt /app/ui/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/ui/backend/requirements.txt

# Install Playwright browsers for integration tests (skip system deps since we have chromium)
RUN playwright install chromium

ENV PYTHONPATH=/app

# Stage 2: Runtime image (lightweight, just copies code)
FROM base AS runtime

# Set environment variables for Selenium to use installed Chromium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Copy the rest of the application
COPY . .

# Ensure /app/data is a directory so bind-mounts work even if the repo has a symlink
RUN rm -rf /app/data && mkdir -p /app/data

CMD ["python", "pipeline/download.py"]
