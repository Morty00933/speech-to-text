# ============================================================
# Stage 1: Model Downloader - скачивает Whisper модели при сборке
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS model-downloader

ENV UV_SYSTEM_PYTHON=1
ENV UV_HTTP_TIMEOUT=300
ENV UV_REQUEST_TIMEOUT=300
WORKDIR /download

# Минимальные зависимости для скачивания моделей
RUN uv pip install faster-whisper huggingface-hub

# ARG для выбора моделей при сборке: "tiny,small", "tiny,small,medium", и т.д.
ARG WHISPER_MODELS="tiny,small"

# Скачиваем модели в /models
RUN mkdir -p /models && \
    python -c "\
import os; \
from huggingface_hub import snapshot_download; \
models = os.environ.get('WHISPER_MODELS', 'tiny,small').split(','); \
[snapshot_download(f'Systran/faster-whisper-{m.strip()}', local_dir=f'/models/faster-whisper-{m.strip()}') for m in models if m.strip()]; \
print(f'Downloaded models: {models}')" && \
    echo "Models downloaded successfully"

# ============================================================
# Stage 2: Worker - финальный образ
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_SYSTEM_PYTHON=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_HTTP_TIMEOUT=300
ENV UV_REQUEST_TIMEOUT=300
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only (современная версия)
RUN uv pip install \
    torch==2.5.1+cpu \
    torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu || \
    (sleep 10 && uv pip install \
    torch==2.5.1+cpu \
    torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu)

# Зависимости проекта
COPY worker/requirements.txt .
RUN uv pip install -r requirements.txt || \
    (sleep 5 && uv pip install -r requirements.txt) || \
    (sleep 10 && uv pip install -r requirements.txt)

COPY common/ ./common/
COPY worker/ .

# Копируем предзагруженные модели из stage 1
COPY --from=model-downloader /models /models

RUN mkdir -p /tmp/audio

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /models /tmp/audio
USER appuser

CMD ["celery", "-A", "celery_app", "worker", \
     "--loglevel=info", \
     "--concurrency=1", \
     "-Q", "transcription"]
