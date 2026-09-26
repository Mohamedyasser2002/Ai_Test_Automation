# ============================================================
# Builder
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# ------------------------------------------------------------
# System dependencies required to build Python packages
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Install uv
# ------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# Use the system Python
ENV UV_PYTHON_DOWNLOADS=0

# ------------------------------------------------------------
# Copy dependency files first
# This improves Docker layer caching
# ------------------------------------------------------------
COPY pyproject.toml uv.lock ./

# ------------------------------------------------------------
# Install project dependencies only
# Do not install the project itself yet
# ------------------------------------------------------------
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --locked \
    --no-install-project \
    --no-dev

# ------------------------------------------------------------
# Copy application source
# ------------------------------------------------------------
COPY src/ ./src/
COPY main.py ./

# ------------------------------------------------------------
# Install the project itself
# ------------------------------------------------------------
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --locked \
    --no-dev \
    --no-editable

# ------------------------------------------------------------
# Install Playwright Chromium + Linux dependencies
# ------------------------------------------------------------
RUN /app/.venv/bin/python -m playwright install --with-deps chromium


# ============================================================
# Production
# ============================================================
FROM python:3.11-slim AS production

WORKDIR /app

# ------------------------------------------------------------
# Runtime system dependencies
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxshmfence1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Copy uv virtual environment
# ------------------------------------------------------------
COPY --from=builder /app/.venv /app/.venv

# ------------------------------------------------------------
# Copy Playwright browsers
# ------------------------------------------------------------
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Playwright browser location
ENV PLAYWRIGHT_BROWSERS_PATH="/root/.cache/ms-playwright"

# ------------------------------------------------------------
# Application
# ------------------------------------------------------------
COPY src/ ./src/
COPY main.py ./
COPY frontend/ ./frontend/

# ------------------------------------------------------------
# Runtime directories
# ------------------------------------------------------------
RUN mkdir -p \
    artifacts/screenshots \
    artifacts/traces \
    artifacts/reports \
    data

# ------------------------------------------------------------
# Port
# ------------------------------------------------------------
EXPOSE 8080

# ------------------------------------------------------------
# Start FastAPI
# ------------------------------------------------------------
CMD ["uvicorn", "src.api.dashboard:app", "--host", "0.0.0.0", "--port", "8080"]