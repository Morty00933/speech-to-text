# Speech-to-Text Pipeline

Производственная микросервисная платформа для транскрибации аудио с диаризацией спикеров на базе Faster-Whisper и pyannote.audio.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791)
![Redis](https://img.shields.io/badge/Redis-7-DC382D)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Возможности

- **Высокоточная транскрибация** через Faster-Whisper (CTranslate2) — в 2–4 раза быстрее оригинального Whisper, поддержка 99 языков
- **Диаризация спикеров** — определяет «кто и когда говорил» через pyannote.audio 3.1
- **Несколько форматов вывода** — JSON, субтитры SRT, WebVTT, plain text
- **Обработка длинного аудио** — автоматическое разбиение записей >30 мин с перекрытием 30 с
- **Асинхронная обработка задач** — Celery + Redis с отслеживанием прогресса в реальном времени
- **WebSocket-стриминг** — подпишитесь на события прогресса через `ws://api/ws/jobs/{id}`
- **Двойная аутентификация** — API-ключ (`X-API-Key`) или JWT Bearer-токен (`POST /auth/token`)
- **Широкий формат поддержки** — MP3, WAV, FLAC, OGG, M4A, OPUS, WebM (конвертация через ffmpeg)
- **S3-совместимое хранилище** — MinIO для аудио и результатов
- **Наблюдаемость** — метрики Prometheus + готовые дашборды Grafana
- **GPU-ускорение** — поддержка CUDA с вычислениями float16 (ускорение в 5–20 раз)
- **Готовность к Kubernetes** — Helm-чарты, health-пробы, горизонтальное масштабирование

## Архитектура

```
                    ┌───────────────────┐
                    │   Nginx (SPA)     │ :8501
                    │  Статический UI + │
                    │  обратный прокси  │
                    └────────┬──────────┘
                             │
                    ┌────────▼──────────┐
                    │   FastAPI (API)   │ :8000
                    │  Авторизация,     │
                    │  валидация, лимит │
                    └──┬─────┬──────┬──┘
                       │     │      │
         ┌─────────────┘     │      └──────────────┐
         ▼                   ▼                      ▼
  ┌─────────────┐    ┌─────────────┐       ┌─────────────┐
  │ PostgreSQL  │    │    Redis    │       │    MinIO    │
  │ (метаданные)│    │  (брокер)   │       │ (файлы S3)  │
  └─────────────┘    └──────┬──────┘       └─────────────┘
                            │
                     ┌──────▼──────┐
                     │   Celery    │
                     │   Worker    │
                     └──┬───┬───┬──┘
                        │   │   │
                        ▼   ▼   ▼
              Faster   Silero  pyannote
              Whisper   VAD    .audio
```

### Поток данных

1. Клиент загружает аудио через REST API или веб-интерфейс
2. API валидирует входные данные, сохраняет файл в MinIO, создаёт задачу в PostgreSQL
3. Celery Worker забирает задачу из очереди Redis
4. Аудио предобрабатывается (нормализация, ресемплинг до 16 кГц)
5. Faster-Whisper транскрибирует с автоопределением языка
6. pyannote.audio выполняет диаризацию спикеров (опционально)
7. Постпроцессор восстанавливает пунктуацию и форматирует вывод
8. Результат сохраняется в MinIO, статус задачи обновляется на `completed`
9. Клиент запрашивает результат через `/jobs/{id}/result`

## Быстрый старт

### Требования

- Docker & Docker Compose
- 8 ГБ RAM минимум
- NVIDIA GPU + CUDA 11.8+ (опционально, для ускорения)

### 1. Клонирование и настройка

```bash
git clone https://github.com/Morty00933/speech-to-text-pipeline.git
cd speech-to-text-pipeline
cp .env.example .env
```

### 2. Сборка и запуск

```bash
# CPU-версия (по умолчанию)
make dev

# Загрузка модели Whisper (обязательно перед первой транскрибацией)
make download-model-tiny     # 75 МБ  — быстрый, базовое качество
make download-model-small    # 500 МБ — хороший баланс
make download-model-medium   # 1.5 ГБ — высокое качество
```

### 3. Доступ к сервисам

| Сервис | URL | Данные |
|--------|-----|--------|
| Веб-интерфейс | http://localhost:8501 | — |
| API-документация (Swagger) | http://localhost:8000/docs | — |
| Grafana | http://localhost:3000 | admin / admin |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| Prometheus | http://localhost:9090 | — |

---

## Аутентификация

API поддерживает два взаимозаменяемых метода аутентификации:

### Вариант 1 — API-ключ

```bash
curl -H "X-API-Key: dev-api-key" http://localhost:8000/jobs/
```

### Вариант 2 — JWT Bearer-токен

Обменяйте API-ключ на короткоживущий JWT (по умолчанию: 60 мин) и используйте его в последующих запросах:

```bash
# 1. Получить токен
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "dev-api-key"}' | jq -r .access_token)

# 2. Использовать токен
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/jobs/
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

> **В продакшене**: задайте `JWT_SECRET_KEY` через переменную окружения (`openssl rand -hex 32`).

---

## WebSocket — прогресс в реальном времени

Подключитесь по WebSocket для получения событий прогресса транскрибации без поллинга:

```javascript
// JavaScript
const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Прогресс: ${data.progress}% — ${data.current_step}`);
  if (["completed", "failed", "cancelled"].includes(data.status)) {
    ws.close();
  }
};
```

```python
# Python (библиотека websockets)
import asyncio, json, websockets

async def watch_job(job_id: str):
    uri = f"ws://localhost:8000/ws/jobs/{job_id}"
    async with websockets.connect(uri) as ws:
        async for message in ws:
            data = json.loads(message)
            print(f"{data['progress']}% — {data['current_step']}")
            if data["status"] in ("completed", "failed"):
                break

asyncio.run(watch_job("your-job-id"))
```

**Формат события:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 60,
  "current_step": "транскрибация чанк 2/4",
  "error_message": null
}
```

---

## Использование API

Все эндпоинты требуют заголовок `X-API-Key` или `Authorization: Bearer <token>`.

### Загрузка и транскрибация

```bash
curl -X POST http://localhost:8000/transcribe/file \
  -H "X-API-Key: dev-api-key" \
  -F "file=@recording.mp3" \
  -F "model_size=small" \
  -F "enable_diarization=true"
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2026-02-15T10:30:00Z"
}
```

### Проверка прогресса

```bash
curl -H "X-API-Key: dev-api-key" \
  http://localhost:8000/jobs/{job_id}
```

```json
{
  "job_id": "550e8400-...",
  "status": "processing",
  "progress": 60,
  "current_step": "постобработка",
  "estimated_time_remaining": 12
}
```

### Получение результата

```bash
curl -H "X-API-Key: dev-api-key" \
  http://localhost:8000/jobs/{job_id}/result
```

```json
{
  "text": "Привет, это тестовая запись.",
  "segments": [
    {
      "start": 0.0,
      "end": 3.2,
      "text": "Привет, это тестовая запись.",
      "speaker": "SPEAKER_00",
      "confidence": -0.38
    }
  ],
  "metadata": {
    "language": "ru",
    "duration": 3.5,
    "processing_time": 1.2,
    "model_used": "small"
  }
}
```

### Все эндпоинты

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `POST` | `/auth/token` | Обмен API-ключа на JWT-токен |
| `POST` | `/transcribe/file` | Загрузка аудиофайла (MP3, WAV, FLAC, OGG, M4A, OPUS, WebM) |
| `POST` | `/transcribe/url` | Транскрибация по URL |
| `POST` | `/transcribe/batch` | Пакетная транскрибация (несколько URL) |
| `GET` | `/jobs/{id}` | Статус задачи + прогресс |
| `GET` | `/jobs/{id}/result` | Результат транскрибации |
| `DELETE` | `/jobs/{id}` | Отмена задачи |
| `GET` | `/jobs/` | Список задач (с пагинацией и фильтрами) |
| `GET` | `/jobs/models` | Доступные модели + статус загрузки |
| `WS` | `/ws/jobs/{id}` | WebSocket-стрим прогресса в реальном времени |
| `GET` | `/health` | Здоровье сервисов (PostgreSQL, Redis, MinIO) |
| `GET` | `/health/live` | Kubernetes liveness probe |
| `GET` | `/health/ready` | Kubernetes readiness probe |
| `GET` | `/metrics` | Метрики Prometheus |

### Пример на Python

```python
import requests
import time

API = "http://localhost:8000"
HEADERS = {"X-API-Key": "dev-api-key"}

# Отправить задачу на транскрибацию
with open("audio.mp3", "rb") as f:
    r = requests.post(
        f"{API}/transcribe/file",
        headers=HEADERS,
        files={"file": f},
        data={"model_size": "small", "enable_diarization": "true"},
    )
job_id = r.json()["job_id"]

# Поллинг до завершения
while True:
    status = requests.get(f"{API}/jobs/{job_id}", headers=HEADERS).json()
    if status["status"] in ("completed", "failed"):
        break
    print(f"Прогресс: {status['progress']}% — {status.get('current_step', '')}")
    time.sleep(2)

# Получить результат
result = requests.get(f"{API}/jobs/{job_id}/result", headers=HEADERS).json()
print(result["text"])

for seg in result.get("segments", []):
    speaker = seg.get("speaker", "")
    print(f"[{speaker}] {seg['start']:.1f}s - {seg['end']:.1f}s: {seg['text']}")
```

---

## Модели Whisper

| Модель | Параметры | Размер | Скорость CPU* | Качество | Применение |
|--------|-----------|--------|---------------|----------|------------|
| `tiny` | 39M | 75 МБ | ~3 с/мин | Базовое | Черновики, тестирование |
| `base` | 74M | 150 МБ | ~4 с/мин | Среднее | Простые записи |
| `small` | 244M | 500 МБ | ~9 с/мин | Хорошее | Общего назначения |
| `medium` | 769M | 1.5 ГБ | ~18 с/мин | Высокое | Профессиональная транскрибация |
| `large-v3` | 1550M | 3 ГБ | ~30 с/мин | Лучшее | Сложное аудио, акценты |

*Время обработки на 1 минуту аудио на CPU. GPU даёт ускорение в 5–20 раз.

---

## GPU-поддержка

```bash
# Требования: NVIDIA GPU, CUDA 11.8+, nvidia-container-toolkit

# Сборка и запуск GPU-версии
make gpu

# Только сборка
make build-gpu
```

GPU-воркер использует тип вычислений `float16` и автоматически определяет доступную VRAM для выбора оптимального устройства.

---

## Структура проекта

```
speech-to-text-pipeline/
├── services/
│   ├── api/                    # FastAPI REST API
│   │   ├── app.py              # Точка входа, middleware
│   │   ├── auth.py             # Аутентификация по API-ключу (SHA-256)
│   │   ├── schemas.py          # Pydantic v2 модели запросов/ответов
│   │   ├── Dockerfile
│   │   └── routes/
│   │       ├── health.py       # Health + K8s пробы
│   │       ├── transcribe.py   # /transcribe/* эндпоинты
│   │       ├── jobs.py         # /jobs/* эндпоинты
│   │       └── ws.py           # WebSocket прогресс
│   │
│   ├── worker/                 # Celery Worker
│   │   ├── celery_app.py       # Celery + конфигурация Redis
│   │   ├── tasks.py            # Задача транскрибации с логикой повтора
│   │   ├── Dockerfile          # CPU-образ
│   │   └── Dockerfile.gpu      # GPU-образ (CUDA 12.4 + cuDNN 9)
│   │
│   ├── transcriber/            # Движок транскрибации
│   │   ├── engine.py           # Обёртка Faster-Whisper
│   │   ├── preprocessor.py     # Нормализация аудио, Silero VAD
│   │   ├── postprocessor.py    # Пунктуация, форматирование SRT/VTT
│   │   └── diarizer.py         # Диаризация спикеров (pyannote)
│   │
│   ├── nginx/                  # Nginx + SPA фронтенд
│   │   ├── nginx.conf
│   │   └── frontend/index.html
│   │
│   └── common/                 # Общие модули
│       ├── config.py           # Pydantic Settings (переменные окружения)
│       ├── database.py         # SQLAlchemy 2.0 ORM
│       ├── storage.py          # MinIO клиент с retry-логикой
│       ├── celery_client.py    # Общий экземпляр Celery
│       ├── models_registry.py  # Реестр метаданных моделей Whisper
│       ├── metrics.py          # Определения метрик Prometheus
│       └── logging_config.py   # Структурированный JSON / цветной лог
│
├── infra/
│   └── helm/stt-pipeline/      # Kubernetes Helm-чарты
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/          # K8s deployments, services, PVC
│
├── monitoring/
│   ├── prometheus/prometheus.yml
│   └── grafana/provisioning/   # Готовые дашборды + источники данных
│
├── scripts/
│   ├── init-db.sql             # Схема PostgreSQL (enum, таблицы, индексы, триггеры)
│   ├── migrate-boolean-columns.sql
│   ├── benchmark.py            # Бенчмарк производительности
│   └── download_models.py      # Утилита загрузки моделей
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── docker-compose.yml          # Основная оркестрация (9 сервисов)
├── docker-compose.gpu.yml      # GPU-override
├── Makefile                    # Команды разработчика
├── pyproject.toml              # Метаданные проекта + зависимости
└── .env.example                # Шаблон переменных окружения
```

---

## Технологический стек

| Слой | Технология | Назначение |
|------|-----------|------------|
| **API** | FastAPI 0.109 | REST API, OpenAPI-документация, async I/O |
| **Очередь задач** | Celery 5.3 + Redis 7 | Асинхронная обработка, повторы |
| **База данных** | PostgreSQL 15 | Метаданные задач, отслеживание статусов |
| **Хранилище** | MinIO | S3-совместимое хранение аудио и результатов |
| **Транскрибация** | Faster-Whisper 1.1 | Оптимизированный Whisper (CTranslate2) |
| **Диаризация** | pyannote.audio 3.1 | Идентификация спикеров |
| **VAD** | Silero VAD | Детектор голосовой активности |
| **Фронтенд** | HTML5/CSS3/JS SPA | Современный тёмный веб-интерфейс |
| **Прокси** | Nginx 1.25 | Статические файлы + API-прокси |
| **Мониторинг** | Prometheus + Grafana | Сбор метрик + дашборды |
| **Упаковка** | Docker Compose | Оркестрация мультисервиса |
| **Оркестрация** | Helm 3 | Деплой в Kubernetes |
| **Среда выполнения** | Python 3.12 + uv | Быстрое управление зависимостями |

---

## Наблюдаемость

### Метрики Prometheus (`GET /metrics`)

| Метрика | Тип | Описание |
|---------|-----|----------|
| `stt_transcription_requests_total` | Counter | Запросы по статусу, модели, формату |
| `stt_transcription_duration_seconds` | Histogram | Распределение времени обработки |
| `stt_audio_duration_seconds` | Histogram | Распределение длительности входного аудио |
| `stt_active_jobs` | Gauge | Текущее количество обрабатываемых задач |
| `stt_jobs_completed_total` | Counter | Завершённые задачи по результату |
| `stt_api_request_duration_seconds` | Histogram | Задержка API-эндпоинтов |
| `stt_gpu_memory_usage_bytes` | Gauge | Использование VRAM GPU |
| `stt_model_loaded` | Gauge | Статус загрузки модели |

### Grafana

Преднастроенные дашборды с панелями для частоты запросов, уровня ошибок, времени обработки, глубины очереди и утилизации ресурсов. Доступны на http://localhost:3000 после `make dev`.

---

## Безопасность

- **Аутентификация по API-ключу** — SHA-256 хэширование, защита от timing-атак
- **SSRF-защита** — транскрибация по URL блокирует обращения к внутренним/приватным адресам
- **Rate limiting** — настраиваемые лимиты для каждого эндпоинта (по умолчанию: 100/мин)
- **Валидация входных данных** — тип файла, размер, код языка, параметры запроса
- **Контейнеры без root** — все сервисы запускаются от непривилегированного `appuser`
- **Секреты через переменные окружения** — никаких захардкоженных учётных данных в исходном коде

---

## Конфигурация

Ключевые переменные окружения (полный список в `.env.example`):

```bash
# API
API_KEY=your-secure-key         # Ключ аутентификации API
RATE_LIMIT=100/minute           # Порог rate limiting
MAX_FILE_SIZE_MB=500            # Максимальный размер загружаемого файла

# Модели
DEFAULT_MODEL_SIZE=tiny         # Модель Whisper по умолчанию
HF_TOKEN=hf_xxxxx              # HuggingFace токен (для диаризации)

# GPU
CUDA_VISIBLE_DEVICES=0          # Индекс GPU-устройства

# База данных
DATABASE_URL=postgresql://stt:stt@postgres:5432/stt

# Мониторинг
GRAFANA_PASSWORD=admin
LOG_LEVEL=INFO
LOG_FORMAT=json                 # json (production) или text (development)
```

---

## Команды Makefile

```bash
# Сборка и запуск
make dev                  # Сборка + запуск всех сервисов (CPU)
make gpu                  # Сборка + запуск с GPU-поддержкой
make build                # Только сборка Docker-образов
make rebuild              # Пересборка без кэша

# Модели
make download-model-tiny  # Загрузить конкретную модель
make download-models      # Загрузить все модели

# Управление
make status               # Статус сервисов
make logs                 # Следить за логами (api, worker)
make health               # Проверка здоровья всех сервисов
make down                 # Остановить и удалить контейнеры
make clean                # Удалить контейнеры + тома

# Разработка
make test                 # Запустить тесты
make shell-api            # Шелл в контейнер API
make shell-worker         # Шелл в контейнер Worker
make db-shell             # Интерактивная консоль PostgreSQL
make migrate              # Запустить миграции БД
```

---

## Решение проблем

| Проблема | Решение |
|---------|---------|
| Модель не найдена | `make download-model-tiny` |
| Worker зависает при старте | Проверьте `make logs-worker` — может идти загрузка модели |
| API возвращает 503 | Убедитесь, что Redis запущен: `docker compose ps` |
| Нехватка памяти | Используйте меньшую модель (`tiny` или `small`) |
| GPU не определяется | Проверьте `nvidia-smi`, переменную `CUDA_VISIBLE_DEVICES` |

```bash
# Отладочные команды
make logs                                    # Логи основных сервисов
make health                                  # Проверка здоровья
docker compose exec redis redis-cli ping     # Проверка Redis
docker compose exec postgres pg_isready      # Проверка PostgreSQL
make db-shell                                # Консоль PostgreSQL
```

---

## Лицензия

MIT License

## Благодарности

- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — оптимизированный Whisper на CTranslate2
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) — диаризация спикеров
- [Silero VAD](https://github.com/snakers4/silero-vad) — детектор голосовой активности
- [FastAPI](https://fastapi.tiangolo.com/) — современный Python веб-фреймворк
