# NOVA — Multi-stage Docker build (Linux, excludes Windows-only modules)
# Deployment fix: Provides a containerized environment for running NOVA
# with Ollama and ChromaDB, excluding pywin32 and other Windows-only deps.

FROM python:3.11-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ffmpeg \
    portaudio19-dev \
    libsndfile1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# -----------------------------------
# Dependency layer (cached separately)
# -----------------------------------
FROM base AS deps

COPY requirements.lock .

# Install Python deps — skip Windows-only packages
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.lock

# Install Playwright browsers
RUN python -m playwright install chromium --with-deps || true

# -----------------------------------
# Runtime image
# -----------------------------------
FROM deps AS runtime

COPY . .

# Create required directories
RUN mkdir -p exports logs assets

# Environment defaults (override with .env or docker-compose)
ENV PYTHONUNBUFFERED=1 \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OMNIPARSER_SERVER_URL=http://omniparser:8000 \
    PROACTIVE_WATCHER_ENABLED=false \
    PHONE_WATCHER_ENABLED=false \
    AUTONOMY_ENABLED=false

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ps aux | grep 'python3 main.py' | grep -v grep || exit 1

CMD ["python3", "main.py"]
