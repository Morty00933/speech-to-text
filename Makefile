# Speech-to-Text Pipeline - Makefile
# CPU version by default (fast build ~15 min)
# GPU version for faster transcription (build ~60+ min)

.PHONY: help dev dev-gpu build build-gpu logs logs-api logs-worker logs-nginx logs-all test clean

SHELL := C:/PROGRA~1/Git/usr/bin/bash.exe
export PATH := /usr/bin:/mingw64/bin:$(PATH)

# Whisper models to embed in Docker (comma-separated)
# Usage: WHISPER_MODELS=tiny,small,medium make build
WHISPER_MODELS ?= tiny,small

# ============================================
# HELP
# ============================================
help:
	@echo ""
	@echo "================================================================="
	@echo "        Speech-to-Text Pipeline - Commands"
	@echo "================================================================="
	@echo ""
	@echo "  First run (recommended):"
	@echo "    make dev                 - Build + start"
	@echo "    make download-model-tiny - Download tiny model (75MB)"
	@echo ""
	@echo "  Models (download BEFORE transcription):"
	@echo "    make download-model-tiny   - 75MB, fast, basic quality"
	@echo "    make download-model-small  - 500MB, good balance"
	@echo "    make download-model-medium - 1.5GB, high quality"
	@echo "    make download-models       - All models at once"
	@echo ""
	@echo "  GPU version (NVIDIA GPU):"
	@echo "    make gpu         - Start GPU version"
	@echo "    make build-gpu   - Build GPU images"
	@echo ""
	@echo "  Management:"
	@echo "    make down        - Stop all services"
	@echo "    make logs        - Show logs"
	@echo "    make status      - Service status"
	@echo "    make clean       - Remove containers and volumes"
	@echo "    make migrate     - Run DB migration (VARCHAR→BOOLEAN columns)"
	@echo ""
	@echo "  After start:"
	@echo "    Frontend UI:  http://localhost:8501"
	@echo "    API Docs:     http://localhost:8000/docs"
	@echo ""

# ============================================
# CPU VERSION (Default - Fast Build)
# ============================================
dev: build
	@echo "Starting CPU version..."
	docker compose up -d
	@echo ""
	@echo "Services started!"
	@echo "  Frontend: http://localhost:8501"
	@echo "  API:      http://localhost:8000/docs"
	@echo ""

build:
	@echo "Building CPU images with models: $(WHISPER_MODELS)..."
	WHISPER_MODELS=$(WHISPER_MODELS) docker compose build --build-arg WHISPER_MODELS=$(WHISPER_MODELS)

rebuild:
	@echo "Rebuilding CPU images without cache (models: $(WHISPER_MODELS))..."
	WHISPER_MODELS=$(WHISPER_MODELS) docker compose build --no-cache --build-arg WHISPER_MODELS=$(WHISPER_MODELS)

# ============================================
# GPU VERSION (NVIDIA CUDA - Slow Build)
# ============================================
gpu: build-gpu
	@echo "Starting GPU version with CUDA..."
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
	@echo ""
	@echo "Services started with GPU!"
	@echo "  Frontend: http://localhost:8501"
	@echo "  API:      http://localhost:8000/docs"
	@echo ""

build-gpu:
	@echo "Building GPU images with models: $(WHISPER_MODELS)..."
	@echo ""
	@echo "GPU image is large due to:"
	@echo "  - CUDA Toolkit (~1.5GB)"
	@echo "  - cuDNN libraries (~800MB)"
	@echo "  - PyTorch with CUDA (~2GB)"
	@echo ""
	docker build -f services/worker/Dockerfile.gpu --build-arg WHISPER_MODELS=$(WHISPER_MODELS) -t stt-worker-gpu services/
	docker compose build api nginx

rebuild-gpu:
	@echo "Rebuilding GPU images without cache (models: $(WHISPER_MODELS))..."
	docker build -f services/worker/Dockerfile.gpu --build-arg WHISPER_MODELS=$(WHISPER_MODELS) -t stt-worker-gpu --no-cache services/

# ============================================
# MANAGEMENT
# ============================================
down:
	docker compose down

stop:
	docker compose stop

start:
	docker compose start

restart:
	docker compose restart

status:
	@echo ""
	@docker compose ps
	@echo ""

# ============================================
# LOGS (main services only, no monitoring)
# ============================================
logs:
	docker compose logs -f api worker nginx

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

logs-nginx:
	docker compose logs -f nginx

logs-all:
	docker compose logs -f

# ============================================
# TESTING
# ============================================
test:
	docker compose run --rm api pytest tests/ -v

test-quick:
	@echo "Quick API test..."
	@curl -s http://localhost:8000/health | python -m json.tool || echo "API is not running"

# ============================================
# MODELS - Pre-download for fast start
# ============================================
download-models:
	@echo "Downloading all Whisper models (tiny, base, small, medium)..."
	@echo "  This will take ~10-15 minutes (depends on internet)"
	@echo ""
	docker compose run --rm worker python -c "from huggingface_hub import snapshot_download; \
[snapshot_download(f'Systran/faster-whisper-{m}', local_dir=f'/models/faster-whisper-{m}') \
for m in ['tiny', 'base', 'small', 'medium']]"
	@echo ""
	@echo "All models downloaded to ./models/"

download-model-tiny:
	@echo "Downloading Whisper tiny (~75MB, fastest)..."
	docker compose run --rm worker python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Systran/faster-whisper-tiny', local_dir='/models/faster-whisper-tiny')"
	@echo "Model tiny is ready"

download-model-base:
	@echo "Downloading Whisper base (~150MB)..."
	docker compose run --rm worker python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Systran/faster-whisper-base', local_dir='/models/faster-whisper-base')"
	@echo "Model base is ready"

download-model-small:
	@echo "Downloading Whisper small (~500MB, good balance)..."
	docker compose run --rm worker python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Systran/faster-whisper-small', local_dir='/models/faster-whisper-small')"
	@echo "Model small is ready"

download-model-medium:
	@echo "Downloading Whisper medium (~1.5GB, high quality)..."
	docker compose run --rm worker python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Systran/faster-whisper-medium', local_dir='/models/faster-whisper-medium')"
	@echo "Model medium is ready"

# ============================================
# UTILITIES
# ============================================
clean:
	@echo "Cleaning Docker..."
	docker compose down -v --rmi local
	rm -rf models/*.pt models/*.bin
	@echo "Cleanup complete"

clean-all:
	@echo "Full Docker cleanup (including all images)..."
	docker compose down -v --rmi all
	docker system prune -f
	@echo "Full cleanup complete"

shell-worker:
	docker compose exec worker bash

shell-api:
	docker compose exec api bash

# ============================================
# DATABASE
# ============================================
db-shell:
	docker compose exec postgres psql -U stt -d stt

migrate:
	@echo "Running database migration (VARCHAR->BOOLEAN columns)..."
	docker compose exec postgres psql -U stt -d stt -f /docker-entrypoint-initdb.d/migrate-boolean-columns.sql || \
	docker compose exec -T postgres psql -U stt -d stt < scripts/migrate-boolean-columns.sql
	@echo "Migration complete."

# ============================================
# HEALTH CHECK
# ============================================
health:
	@echo "Service health check..."
	@echo ""
	@echo "API:"
	@curl -s http://localhost:8000/health 2>/dev/null | python -m json.tool || echo "  API unavailable"
	@echo ""
	@echo "Frontend:"
	@curl -s -o /dev/null -w "  Status: %{http_code}\n" http://localhost:8501 2>/dev/null || echo "  Frontend unavailable"

# ============================================
# INFO
# ============================================
info:
	@echo ""
	@echo "Docker image info:"
	@echo ""
	@docker images | grep -E "stt-|speech" || echo "No images found"
	@echo ""
	@echo "Image sizes:"
	@docker system df
