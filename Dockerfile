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

COPY requirements.txt .

# Install Python deps — skip Windows-only packages
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir \
        openai==1.3.5 \
        google-generativeai \
        faster-whisper \
        pyttsx3 \
        gTTS \
        pynput \
        Pillow==11.3.0 \
        opencv-python-headless==4.8.1.78 \
        numpy==1.26.4 \
        pyautogui \
        playwright \
        requests==2.32.5 \
        beautifulsoup4 \
        duckduckgo-search \
        rank-bm25==0.2.2 \
        mem0ai \
        chromadb \
        sentence-transformers \
        pypdf \
        python-docx \
        qrcode[pil] \
        rich==14.3.3 \
        APScheduler==3.10.4 \
        SQLAlchemy==2.0.29 \
        pydantic==2.12.5 \
        python-dotenv==1.0.1 \
        loguru \
        psutil==5.9.3 \
        huggingface_hub==0.36.2 \
        pytest==8.4.2

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

CMD ["python3", "main.py"]
