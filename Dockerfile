# Evidence Lab Python image: API, MCP server and pipeline.
#
# Targets:
#   runtime  what production runs and what is published to Docker Hub and GHCR.
#   test     runtime plus Chromium and Playwright's browser, for the integration
#            tests (tests/integration/test_pipeline_ui.py) and the dev stack.
#
# BuildKit builds only the stages the chosen target needs, so `--target runtime`
# never downloads the test browsers.

# Stage 1: system packages and Python dependencies shared by every target
FROM python:3.11-slim AS base

# LibreOffice converts Word and spreadsheet files. The two font packages stay
# here because LibreOffice uses installed fonts when it renders documents.
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    git \
    libreoffice-writer \
    libreoffice-calc \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install all Python dependencies (the expensive part)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ui/backend/requirements.txt /app/ui/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/ui/backend/requirements.txt

ENV PYTHONPATH=/app

# Stage 2: browsers for the integration tests (never shipped)
FROM base AS test-tools

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
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

# Playwright's own Chromium build (system deps installed above)
RUN playwright install chromium

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Stage 3: production image (published)
FROM base AS runtime

COPY . .

# Ensure /app/data is a directory so bind-mounts work even if the repo has a symlink
RUN rm -rf /app/data && mkdir -p /app/data

CMD ["python", "pipeline/download.py"]

# Stage 4: test image (runtime code plus the test browsers)
FROM test-tools AS test

COPY . .

RUN rm -rf /app/data && mkdir -p /app/data

CMD ["python", "pipeline/download.py"]
