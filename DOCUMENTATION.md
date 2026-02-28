# Speech-to-Text Pipeline - Полный Гайд

## Содержание

1. [Обзор проекта](#1-обзор-проекта)
2. [Архитектура системы](#2-архитектура-системы)
3. [Технологический стек](#3-технологический-стек)
4. [Установка и запуск](#4-установка-и-запуск)
5. [Структура проекта](#5-структура-проекта)
6. [API Сервис (FastAPI)](#6-api-сервис-fastapi)
7. [Worker Сервис (Celery)](#7-worker-сервис-celery)
8. [Transcriber - Движок транскрипции](#8-transcriber---движок-транскрипции)
9. [Frontend (Streamlit)](#9-frontend-streamlit)
10. [База данных (PostgreSQL)](#10-база-данных-postgresql)
11. [Очередь задач (Redis + Celery)](#11-очередь-задач-redis--celery)
12. [Хранилище файлов (MinIO)](#12-хранилище-файлов-minio)
13. [Мониторинг (Prometheus + Grafana)](#13-мониторинг-prometheus--grafana)
14. [Docker конфигурация](#14-docker-конфигурация)
15. [Библиотеки и зависимости](#15-библиотеки-и-зависимости)
16. [Примеры использования API](#16-примеры-использования-api)
17. [Устранение неполадок](#17-устранение-неполадок)

---

## 1. Обзор проекта

### Что это?

Speech-to-Text Pipeline - это полноценная система для преобразования аудио в текст с поддержкой:

- **Транскрипции** - распознавание речи на 99+ языках
- **Диаризации** - определение кто говорит (SPEAKER_00, SPEAKER_01, и т.д.)
- **Пунктуации** - автоматическая расстановка знаков препинания
- **Различных форматов** - JSON, SRT (субтитры), VTT, TXT

### Основные возможности

| Функция | Описание |
|---------|----------|
| Загрузка файлов | MP3, WAV, FLAC, OGG, M4A, WebM до 500MB |
| Модели Whisper | tiny, base, small, medium, large-v3 |
| Языки | 99+ языков с автоопределением |
| Диаризация | Определение до 20 говорящих |
| Форматы вывода | JSON, SRT, VTT, TXT |
| API | REST API с документацией Swagger |
| UI | Веб-интерфейс на Streamlit |

---

## 2. Архитектура системы

### Схема взаимодействия компонентов

```
┌─────────────────────────────────────────────────────────────────────┐
│                           КЛИЕНТ                                     │
│                  (Браузер / API запросы)                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                     │
│                    Streamlit (порт 8501)                            │
│   - Веб-интерфейс для загрузки файлов                               │
│   - Отображение прогресса транскрипции                              │
│   - История задач и результаты                                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           API                                        │
│                    FastAPI (порт 8000)                              │
│   - REST API endpoints                                               │
│   - Аутентификация по API Key                                       │
│   - Rate limiting                                                    │
│   - Валидация запросов                                              │
└─────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  PostgreSQL │      │    Redis    │      │    MinIO    │
│  (метаданные│      │  (очередь   │      │  (файловое  │
│   задач)    │      │   задач)    │      │  хранилище) │
└─────────────┘      └─────────────┘      └─────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          WORKER                                      │
│                    Celery (фоновый)                                 │
│   - Получает задачи из Redis                                        │
│   - Обрабатывает аудио                                              │
│   - Сохраняет результаты                                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Whisper   │      │  pyannote   │      │   Silero    │
│   (STT)     │      │ (диаризация)│      │   (VAD)     │
└─────────────┘      └─────────────┘      └─────────────┘
```

### Поток данных при транскрипции

```
1. Пользователь загружает аудио через UI или API
                    │
                    ▼
2. API валидирует файл (формат, размер)
                    │
                    ▼
3. Файл сохраняется в MinIO (uploads/{job_id}/audio.mp3)
                    │
                    ▼
4. Создается запись в PostgreSQL (статус: QUEUED)
                    │
                    ▼
5. Задача отправляется в Redis очередь
                    │
                    ▼
6. Worker получает задачу из очереди
                    │
                    ▼
7. Worker скачивает файл из MinIO
                    │
                    ▼
8. Preprocessing: нормализация, ресэмплинг в 16kHz
                    │
                    ▼
9. Transcription: Whisper распознает речь
                    │
                    ▼
10. Diarization: pyannote определяет говорящих (опционально)
                    │
                    ▼
11. Postprocessing: пунктуация, форматирование
                    │
                    ▼
12. Результат сохраняется в MinIO (results/{job_id}/transcription.json)
                    │
                    ▼
13. PostgreSQL обновляется (статус: COMPLETED)
                    │
                    ▼
14. Клиент получает результат через API
```

---

## 3. Технологический стек

### Основные технологии

| Компонент | Технология | Назначение |
|-----------|-----------|-----------|
| **API** | FastAPI | Асинхронный REST API сервер |
| **UI** | Streamlit | Веб-интерфейс |
| **Очередь** | Celery + Redis | Фоновая обработка задач |
| **БД** | PostgreSQL | Хранение метаданных |
| **Хранилище** | MinIO | S3-совместимое хранилище файлов |
| **STT** | Faster-Whisper | Распознавание речи |
| **Диаризация** | pyannote.audio | Определение говорящих |
| **VAD** | Silero VAD | Детектирование речи |
| **Мониторинг** | Prometheus + Grafana | Метрики и дашборды |
| **Контейнеризация** | Docker Compose | Оркестрация сервисов |

### Версии

```yaml
Python: 3.12
FastAPI: 0.109.0
Celery: 5.3.6
Streamlit: 1.31.0
PostgreSQL: 15
Redis: 7
MinIO: latest
faster-whisper: 1.1.0+
pyannote.audio: 3.1+
torch: 2.5.1
```

---

## 4. Установка и запуск

### Требования

**Минимальные:**
- Docker и Docker Compose
- 8GB RAM
- 10GB свободного места

**Для GPU (рекомендуется):**
- NVIDIA GPU с 6GB+ VRAM
- CUDA 11.8+
- nvidia-docker

### Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd speech-to-text-pipeline

# 2. Скопировать конфигурацию
cp .env.example .env

# 3. Запустить сервисы (CPU версия)
make dev

# 4. Скачать модель Whisper
make download-model-tiny    # 75MB, быстрая
# или
make download-model-small   # 500MB, лучше качество
# или
make download-model-medium  # 1.5GB, высокое качество

# 5. Открыть в браузере
# Frontend: http://localhost:8501
# API Docs: http://localhost:8000/docs
```

### Команды Makefile

```bash
# Разработка
make dev              # Сборка + запуск CPU версии
make gpu              # Запуск GPU версии
make build            # Только сборка образов

# Модели
make download-model-tiny    # 75MB
make download-model-base    # 150MB
make download-model-small   # 500MB
make download-model-medium  # 1.5GB
make download-models        # Все модели

# Управление
make start            # Запустить сервисы
make stop             # Остановить сервисы
make down             # Удалить контейнеры
make restart          # Перезапустить
make status           # Показать статус
make logs             # Просмотр логов

# Отладка
make shell-api        # Shell в API контейнере
make shell-worker     # Shell в Worker контейнере
make db-shell         # PostgreSQL консоль

# Очистка
make clean            # Удалить контейнеры и volumes
make clean-all        # Полная очистка
```

---

## 5. Структура проекта

```
speech-to-text-pipeline/
│
├── docker-compose.yml       # Основная конфигурация Docker
├── docker-compose.gpu.yml   # Оверрайд для GPU
├── Makefile                 # Команды управления
├── .env                     # Переменные окружения
├── .env.example             # Пример переменных
│
├── services/                # Микросервисы
│   │
│   ├── api/                 # FastAPI сервис
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app.py           # Точка входа
│   │   ├── auth.py          # Аутентификация
│   │   ├── schemas.py       # Pydantic модели
│   │   └── routes/          # API endpoints
│   │       ├── health.py    # Health checks
│   │       ├── transcribe.py # Транскрипция
│   │       └── jobs.py      # Управление задачами
│   │
│   ├── worker/              # Celery worker
│   │   ├── Dockerfile       # CPU версия
│   │   ├── Dockerfile.gpu   # GPU версия
│   │   ├── requirements.txt
│   │   ├── celery_app.py    # Конфигурация Celery
│   │   └── tasks.py         # Задачи транскрипции
│   │
│   ├── transcriber/         # Движок транскрипции
│   │   ├── engine.py        # Whisper wrapper
│   │   ├── preprocessor.py  # Предобработка аудио
│   │   ├── postprocessor.py # Постобработка текста
│   │   └── diarizer.py      # Диаризация
│   │
│   ├── frontend/            # Streamlit UI
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app.py           # Веб-интерфейс
│   │
│   └── common/              # Общие модули
│       ├── config.py        # Конфигурация
│       ├── database.py      # ORM модели
│       ├── storage.py       # MinIO клиент
│       ├── metrics.py       # Prometheus метрики
│       └── logging_config.py # Логирование
│
├── models/                  # Папка для моделей Whisper
│   └── faster-whisper-*/    # Скачанные модели
│
├── scripts/                 # Вспомогательные скрипты
│   ├── init-db.sql          # Инициализация БД
│   └── download_models.py   # Скачивание моделей
│
├── monitoring/              # Конфигурация мониторинга
│   ├── prometheus.yml
│   └── grafana/
│
└── tests/                   # Тесты
    ├── unit/
    └── integration/
```

---

## 6. API Сервис (FastAPI)

### Файл: `services/api/app.py`

Это главный файл API сервиса. Разберем его по частям:

#### Импорты и инициализация

```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address

# Создание приложения FastAPI
app = FastAPI(
    title="Speech-to-Text API",
    description="API для транскрипции аудио",
    version="1.0.0",
)

# Rate limiter - ограничение запросов
limiter = Limiter(key_func=get_remote_address)
```

**Что это делает:**
- `FastAPI()` - создает приложение
- `Limiter` - защита от DDoS (ограничение 100 запросов/минуту)

#### Middleware (промежуточные обработчики)

```python
# CORS - разрешает запросы с других доменов
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Разрешить все домены
    allow_credentials=True,    # Разрешить cookies
    allow_methods=["*"],       # Разрешить все методы (GET, POST, etc.)
    allow_headers=["*"],       # Разрешить все заголовки
)

# Middleware для логирования запросов
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path}",
                extra={"duration": duration})
    return response
```

**Что это делает:**
- `CORSMiddleware` - позволяет браузеру делать запросы к API
- `logging_middleware` - записывает каждый запрос в лог

#### Lifespan (жизненный цикл)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: при запуске приложения
    logger.info("Starting Speech-to-Text API...")
    init_db()  # Инициализация базы данных
    logger.info("Database initialized")

    yield  # Приложение работает

    # Shutdown: при остановке
    logger.info("Shutting down...")
```

**Что это делает:**
- `init_db()` - создает таблицы в PostgreSQL при первом запуске
- `yield` - приложение работает пока не остановлено

### Файл: `services/api/routes/transcribe.py`

Этот файл содержит endpoints для транскрипции:

#### POST /transcribe/file

```python
@router.post("/file", response_model=TranscribeResponse)
async def transcribe_file(
    file: UploadFile = File(...),           # Загруженный файл
    model_size: str = Form("tiny"),         # Размер модели
    language: str = Form(None),             # Язык (auto если None)
    enable_diarization: bool = Form(False), # Определять говорящих?
    output_format: str = Form("json"),      # Формат вывода
    api_key: str = Depends(verify_api_key), # Проверка API ключа
):
    """
    Загрузить аудио файл и создать задачу транскрипции.
    """

    # 1. Валидация формата файла
    allowed_formats = ["mp3", "wav", "flac", "ogg", "m4a", "webm"]
    ext = file.filename.split(".")[-1].lower()
    if ext not in allowed_formats:
        raise HTTPException(400, f"Формат {ext} не поддерживается")

    # 2. Проверка размера (макс 500MB)
    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(413, "Файл слишком большой")

    # 3. Генерация уникального ID задачи
    job_id = str(uuid.uuid4())

    # 4. Загрузка файла в MinIO
    storage = get_storage()
    audio_path = f"uploads/{job_id}/audio.{ext}"
    storage.upload_bytes(content, audio_path, f"audio/{ext}")

    # 5. Создание записи в БД
    db = get_db_session()
    job = TranscriptionJob(
        id=job_id,
        status=JobStatus.QUEUED,
        audio_path=audio_path,
        model_size=model_size,
        # ... другие поля
    )
    db.add(job)
    db.commit()

    # 6. Отправка задачи в Celery
    transcribe_audio.delay(
        job_id=job_id,
        audio_path=audio_path,
        options={
            "model_size": model_size,
            "language": language,
            "enable_diarization": enable_diarization,
            # ...
        }
    )

    # 7. Возврат информации о задаче
    return TranscribeResponse(
        job_id=job_id,
        status="queued",
        created_at=datetime.utcnow(),
    )
```

**Пошаговое объяснение:**

1. **Валидация** - проверяем что файл нужного формата
2. **Размер** - не больше 500MB
3. **UUID** - уникальный идентификатор задачи
4. **MinIO** - сохраняем файл в хранилище
5. **PostgreSQL** - создаем запись о задаче
6. **Celery** - отправляем в очередь на обработку
7. **Response** - возвращаем ID для отслеживания

### Файл: `services/api/routes/jobs.py`

#### GET /jobs/{job_id}

```python
@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    api_key: str = Depends(verify_api_key),
):
    """
    Получить статус задачи по ID.
    """
    db = get_db_session()
    job = db.query(TranscriptionJob).filter(
        TranscriptionJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(404, "Задача не найдена")

    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status.value,       # "queued", "processing", "completed"
        progress=job.progress or 0,    # 0-100%
        current_step=job.current_step, # "transcribing", "diarizing", etc.
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error_message,
    )
```

#### GET /jobs/{job_id}/result

```python
@router.get("/{job_id}/result", response_model=TranscriptionResult)
async def get_job_result(job_id: str, api_key: str = Depends(verify_api_key)):
    """
    Получить результат завершенной транскрипции.
    """
    db = get_db_session()
    job = db.query(TranscriptionJob).filter(
        TranscriptionJob.id == job_id
    ).first()

    # Проверка что задача завершена
    if job.status != JobStatus.COMPLETED:
        if job.status == JobStatus.PROCESSING:
            # Еще обрабатывается - вернуть 202 с Retry-After
            return Response(status_code=202, headers={"Retry-After": "10"})
        elif job.status == JobStatus.FAILED:
            raise HTTPException(500, job.error_message)

    # Получить результат из MinIO
    storage = get_storage()
    result_bytes = storage.get_file_bytes(job.result_path)
    result_data = json.loads(result_bytes)

    return TranscriptionResult(**result_data)
```

### Файл: `services/api/schemas.py`

Pydantic модели для валидации данных:

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List

# Enum для статусов задачи
class JobStatus(str, Enum):
    QUEUED = "queued"         # В очереди
    PROCESSING = "processing" # Обрабатывается
    COMPLETED = "completed"   # Завершена
    FAILED = "failed"         # Ошибка
    CANCELLED = "cancelled"   # Отменена

# Enum для размеров модели
class ModelSize(str, Enum):
    TINY = "tiny"       # 39M параметров, 1GB VRAM
    BASE = "base"       # 74M параметров, 1GB VRAM
    SMALL = "small"     # 244M параметров, 2GB VRAM
    MEDIUM = "medium"   # 769M параметров, 5GB VRAM
    LARGE_V3 = "large-v3"  # 1550M параметров, 10GB VRAM

# Модель сегмента транскрипции
class Segment(BaseModel):
    start: float = Field(..., description="Начало в секундах")
    end: float = Field(..., description="Конец в секундах")
    text: str = Field(..., description="Текст сегмента")
    speaker: Optional[str] = Field(None, description="ID говорящего")
    confidence: Optional[float] = Field(None, description="Уверенность")

# Модель ответа транскрипции
class TranscriptionResult(BaseModel):
    job_id: str
    status: str
    text: str                           # Полный текст
    segments: List[Segment]             # Сегменты с таймкодами
    metadata: dict                      # Язык, длительность, и т.д.
```

**Что это делает:**
- `Enum` - ограничивает допустимые значения
- `Field(...)` - обязательное поле с описанием
- `Optional[str]` - необязательное поле

### Файл: `services/api/auth.py`

Аутентификация по API ключу:

```python
from fastapi import Header, HTTPException
from common.config import settings
import hashlib

async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """
    Проверить API ключ из заголовка X-API-Key.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header."
        )

    # Сравнение с ключом из настроек
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    return x_api_key

def hash_api_key(api_key: str) -> str:
    """
    Хэширование API ключа для хранения в БД.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()
```

**Что это делает:**
- `Header(...)` - извлекает заголовок из запроса
- Сравнивает с ключом из .env файла
- Возвращает 401 если ключ неверный

---

## 7. Worker Сервис (Celery)

### Файл: `services/worker/celery_app.py`

Конфигурация Celery:

```python
from celery import Celery
from common.config import settings

# Создание приложения Celery
app = Celery(
    "stt_worker",
    broker=settings.redis_url,      # Redis как брокер сообщений
    backend=settings.redis_url,     # Redis для хранения результатов
)

# Конфигурация
app.conf.update(
    # Сериализация
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Очередь
    task_default_queue="transcription",

    # Таймауты
    task_time_limit=3600,        # Максимум 1 час на задачу
    task_soft_time_limit=600,    # Мягкий лимит 10 минут

    # Для GPU: одна задача за раз
    worker_prefetch_multiplier=1,
    worker_concurrency=1,

    # Перезапуск каждые 50 задач (очистка памяти)
    worker_max_tasks_per_child=50,

    # Подтверждение после выполнения
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Импорт задач
from tasks import transcribe_audio
```

**Ключевые параметры:**

| Параметр | Значение | Описание |
|----------|----------|----------|
| `broker` | Redis URL | Где хранить очередь задач |
| `backend` | Redis URL | Где хранить результаты |
| `task_time_limit` | 3600 | Максимум 1 час на задачу |
| `worker_concurrency` | 1 | Одна задача одновременно (для GPU) |
| `task_acks_late` | True | Подтверждение после выполнения |

### Файл: `services/worker/tasks.py`

Главная задача транскрипции:

```python
from celery import Task
from celery_app import app
from common.database import TranscriptionJob, JobStatus, get_db_session
from common.storage import get_storage
from transcriber.engine import TranscriptionEngine

# Базовый класс с ленивой загрузкой моделей
class TranscriptionTask(Task):
    """
    Базовый класс задачи с кэшированием моделей.
    Модели загружаются один раз и переиспользуются.
    """
    _engine = None       # Whisper модель
    _preprocessor = None # Препроцессор
    _diarizer = None     # Диаризатор

    @property
    def engine(self):
        """Ленивая загрузка Whisper модели."""
        if self._engine is None:
            from transcriber.engine import TranscriptionEngine
            self._engine = TranscriptionEngine(
                model_size=settings.default_model_size
            )
            self._engine.load_model()
        return self._engine

# Основная задача
@app.task(
    bind=True,                              # self доступен
    base=TranscriptionTask,                 # Наследование
    max_retries=3,                          # 3 попытки
    name="worker.tasks.transcribe_audio",   # Имя задачи
    soft_time_limit=600,                    # 10 минут soft limit
    time_limit=660,                         # 11 минут hard limit
)
def transcribe_audio(self, job_id: str, audio_path: str, options: dict):
    """
    Главная задача транскрипции.

    Args:
        job_id: UUID задачи
        audio_path: Путь к файлу в MinIO
        options: Параметры транскрипции
    """
    start_time = time.time()
    temp_files = []  # Для очистки временных файлов

    try:
        # 1. Обновить статус: PROCESSING
        update_job_status(job_id, JobStatus.PROCESSING,
                         progress=0, current_step="downloading")

        # 2. Скачать аудио из MinIO
        storage = get_storage()
        local_audio_path = tempfile.mktemp(suffix=".audio")
        storage.download_file(audio_path, local_audio_path)
        temp_files.append(local_audio_path)

        # 3. Получить информацию об аудио
        audio_info = self.preprocessor.get_audio_info(local_audio_path)
        update_job_status(job_id, JobStatus.PROCESSING,
                         progress=10, current_step="preprocessing")

        # 4. Предобработка
        preprocessed_path = self.preprocessor.preprocess(
            local_audio_path,
            remove_silence=False,  # VAD отключен
            normalize=True,        # Нормализация громкости
        )
        if preprocessed_path != local_audio_path:
            temp_files.append(preprocessed_path)

        # 5. Транскрипция
        update_job_status(job_id, JobStatus.PROCESSING,
                         progress=20, current_step="transcribing")

        model_size = options.get("model_size", "tiny")

        # Перезагрузить модель если нужен другой размер
        if self._engine and model_size != self._engine.model_size:
            self._engine = TranscriptionEngine(model_size=model_size)
            self._engine.load_model()

        transcription = self.engine.transcribe(
            preprocessed_path,
            language=options.get("language"),
            word_timestamps=True,
        )

        # 6. Диаризация (опционально)
        if options.get("enable_diarization"):
            update_job_status(job_id, JobStatus.PROCESSING,
                             progress=60, current_step="diarizing")
            # ... код диаризации

        # 7. Постобработка
        update_job_status(job_id, JobStatus.PROCESSING,
                         progress=85, current_step="formatting")
        # ... восстановление пунктуации

        # 8. Сохранение результата
        update_job_status(job_id, JobStatus.PROCESSING,
                         progress=95, current_step="saving")

        result = {
            "text": transcription.text,
            "segments": [segment.__dict__ for segment in transcription.segments],
            "language": transcription.language,
            "duration": transcription.duration,
            "processing_time": time.time() - start_time,
        }

        # Сохранить в MinIO
        result_path = f"results/{job_id}/transcription.json"
        storage.upload_bytes(
            json.dumps(result).encode(),
            result_path,
            "application/json"
        )

        # 9. Обновить БД: COMPLETED
        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            current_step="completed",
            result_path=result_path,
            result_text=transcription.text[:10000],
            processing_time=time.time() - start_time,
        )

        return {"job_id": job_id, "status": "completed"}

    except Exception as e:
        # Обработка ошибки
        logger.error(f"Transcription failed: {e}", exc_info=True)
        update_job_status(job_id, JobStatus.FAILED,
                         error_message=str(e))
        raise

    finally:
        # Очистка временных файлов
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
```

**Этапы обработки:**

| Этап | Progress | Описание |
|------|----------|----------|
| downloading | 0% | Скачивание из MinIO |
| preprocessing | 10% | Нормализация аудио |
| transcribing | 20% | Whisper распознавание |
| diarizing | 60% | Определение говорящих |
| formatting | 85% | Пунктуация, форматирование |
| saving | 95% | Сохранение в MinIO |
| completed | 100% | Готово |

---

## 8. Transcriber - Движок транскрипции

### Файл: `services/transcriber/engine.py`

Wrapper для Faster-Whisper:

```python
from faster_whisper import WhisperModel
import torch

class TranscriptionEngine:
    """
    Движок транскрипции на базе Faster-Whisper.

    Faster-Whisper - это оптимизированная версия Whisper:
    - Использует CTranslate2 (C++ inference)
    - В 2-4 раза быстрее оригинального Whisper
    - Поддержка float16 для экономии VRAM
    """

    # Требования к VRAM для каждой модели
    MODEL_VRAM = {
        "tiny": 1.0,      # 39M параметров
        "base": 1.0,      # 74M параметров
        "small": 2.0,     # 244M параметров
        "medium": 5.0,    # 769M параметров
        "large-v3": 10.0, # 1550M параметров
    }

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "auto",
        compute_type: str = "float16",
    ):
        """
        Инициализация движка.

        Args:
            model_size: Размер модели (tiny, base, small, medium, large-v3)
            device: Устройство (auto, cuda, cpu)
            compute_type: Тип вычислений (float16, int8, float32)
        """
        self.model_size = model_size
        self.device = self._determine_device(device)
        self.compute_type = compute_type if self.device == "cuda" else "float32"
        self.model = None

    def _determine_device(self, device: str) -> str:
        """Автоматическое определение устройства."""
        if device == "auto":
            if torch.cuda.is_available():
                # Проверить достаточно ли VRAM
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                required = self.MODEL_VRAM.get(self.model_size, 5.0)

                if vram_gb >= required:
                    return "cuda"
                else:
                    logger.warning(f"Недостаточно VRAM ({vram_gb}GB < {required}GB)")
                    return "cpu"
            return "cpu"
        return device

    def load_model(self):
        """Загрузить модель Whisper."""
        if self.model is not None:
            return

        logger.info(f"Загрузка Whisper модели: {self.model_size}")

        # Проверить локальную папку с моделью
        local_path = f"/models/faster-whisper-{self.model_size}"
        if os.path.exists(local_path):
            logger.info(f"Найдена локальная модель: {local_path}")
            model_path = local_path
        else:
            logger.info("Модель будет скачана с HuggingFace...")
            model_path = self.model_size

        self.model = WhisperModel(
            model_path,
            device=self.device,
            compute_type=self.compute_type,
            download_root="/models",
            cpu_threads=4,
            num_workers=2,
        )

        logger.info(f"Модель загружена за {time.time() - start:.2f}с")

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        word_timestamps: bool = True,
    ) -> TranscriptionResult:
        """
        Транскрибировать аудио файл.

        Args:
            audio_path: Путь к аудио файлу
            language: Код языка (None = автоопределение)
            word_timestamps: Включить таймкоды слов

        Returns:
            TranscriptionResult с текстом и сегментами
        """
        self.load_model()

        # Транскрипция с оптимальными параметрами
        segments_generator, info = self.model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            beam_size=5,              # Качество vs скорость
            best_of=5,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # Fallback temperatures
            no_speech_threshold=0.9,  # Порог "не речь" (выше = меньше фильтрации)
            word_timestamps=word_timestamps,
            vad_filter=False,         # VAD отключен для песен
        )

        # Собрать сегменты
        segments = []
        for segment in segments_generator:
            segments.append(TranscriptionSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text.strip(),
                words=[
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in (segment.words or [])
                ],
                confidence=segment.avg_logprob,
            ))

        return TranscriptionResult(
            text=" ".join(s.text for s in segments),
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
        )
```

### Параметры модели transcribe()

| Параметр | Значение | Описание |
|----------|----------|----------|
| `beam_size` | 5 | Ширина поиска (больше = лучше, медленнее) |
| `best_of` | 5 | Выбор лучшего из N вариантов |
| `temperature` | [0.0-1.0] | Fallback с увеличением температуры |
| `no_speech_threshold` | 0.9 | Порог обнаружения "не речи" |
| `vad_filter` | False | Фильтр тишины (отключен для музыки) |

### Файл: `services/transcriber/preprocessor.py`

Предобработка аудио:

```python
import librosa
import numpy as np
import torch

class AudioPreprocessor:
    """
    Предобработка аудио перед транскрипцией.

    Функции:
    - Загрузка различных форматов (MP3, WAV, FLAC, etc.)
    - Ресэмплинг в 16kHz (требование Whisper)
    - Нормализация громкости
    - Voice Activity Detection (VAD) - опционально
    """

    TARGET_SAMPLE_RATE = 16000  # Whisper требует 16kHz

    def __init__(self, vad_threshold: float = 0.5):
        """
        Args:
            vad_threshold: Порог VAD (0-1, выше = строже)
        """
        self.vad_threshold = vad_threshold
        self.vad_model = None  # Ленивая загрузка

    def load_audio(self, audio_path: str) -> tuple:
        """
        Загрузить аудио файл.

        librosa автоматически:
        - Определяет формат (mp3, wav, flac, etc.)
        - Конвертирует в моно
        - Ресэмплирует в target sample rate

        Returns:
            (audio_array, sample_rate)
        """
        audio, sr = librosa.load(
            audio_path,
            sr=self.TARGET_SAMPLE_RATE,  # Ресэмплинг в 16kHz
            mono=True,                    # Моно канал
        )

        # Конвертация в float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        return audio, sr

    def normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Нормализация громкости (peak normalization).

        Масштабирует аудио так, чтобы максимальная амплитуда
        была 0.95 (-0.5 dB от максимума).
        """
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val * 0.95
        return audio

    def detect_speech(self, audio: np.ndarray) -> list:
        """
        Определение речевых сегментов с помощью Silero VAD.

        Silero VAD - легковесная модель для определения
        где в аудио есть речь, а где тишина/музыка.

        Returns:
            List[SpeechSegment] с start/end времен
        """
        # Ленивая загрузка модели VAD
        if self.vad_model is None:
            model, utils = torch.hub.load(
                'snakers4/silero-vad',
                'silero_vad',
                trust_repo=True,
            )
            self.vad_model = model
            self.get_speech_timestamps = utils[0]

        # Определение речевых сегментов
        audio_tensor = torch.tensor(audio)
        timestamps = self.get_speech_timestamps(
            audio_tensor,
            self.vad_model,
            sampling_rate=16000,
            threshold=self.vad_threshold,
            min_speech_duration_ms=250,
            min_silence_duration_ms=100,
        )

        return [
            SpeechSegment(start=ts["start"], end=ts["end"])
            for ts in timestamps
        ]

    def preprocess(
        self,
        audio_path: str,
        remove_silence: bool = False,
        normalize: bool = True,
    ) -> str:
        """
        Полный pipeline предобработки.

        Args:
            audio_path: Путь к входному файлу
            remove_silence: Удалять тишину (VAD)
            normalize: Нормализовать громкость

        Returns:
            Путь к обработанному файлу
        """
        # Загрузка
        audio, sr = self.load_audio(audio_path)

        # Нормализация
        if normalize:
            audio = self.normalize_audio(audio)

        # VAD (отключен по умолчанию для песен)
        if remove_silence:
            segments = self.detect_speech(audio, sr)
            if segments:
                audio = self.extract_speech(audio, segments, sr)

        # Сохранение
        output_path = tempfile.mktemp(suffix=".wav")
        sf.write(output_path, audio, sr)

        return output_path
```

### Файл: `services/transcriber/diarizer.py`

Определение говорящих:

```python
class SpeakerDiarizer:
    """
    Диаризация (определение говорящих) с помощью pyannote.audio.

    Требует HF_TOKEN для доступа к модели на HuggingFace.
    Модель: pyannote/speaker-diarization-3.1
    """

    def __init__(self, hf_token: str = None):
        self.hf_token = hf_token or settings.hf_token
        self.model = None

    def load_model(self):
        """Загрузить модель диаризации."""
        if self.model is not None:
            return

        if not self.hf_token:
            raise ValueError("HF_TOKEN требуется для диаризации")

        from pyannote.audio import Pipeline

        self.model = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=self.hf_token,
        )

        # Перенос на GPU если доступен
        if torch.cuda.is_available():
            self.model.to(torch.device("cuda"))

    def diarize(
        self,
        audio_path: str,
        min_speakers: int = 1,
        max_speakers: int = None,
    ) -> list:
        """
        Выполнить диаризацию аудио.

        Args:
            audio_path: Путь к аудио файлу
            min_speakers: Минимум говорящих
            max_speakers: Максимум говорящих (None = без ограничений)

        Returns:
            List[SpeakerSegment] с speaker ID и временами
        """
        self.load_model()

        # Запуск диаризации
        diarization = self.model(
            audio_path,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )

        # Извлечение сегментов
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(SpeakerSegment(
                start=turn.start,
                end=turn.end,
                speaker=speaker,  # "SPEAKER_00", "SPEAKER_01", etc.
            ))

        return segments

    def align_with_transcription(
        self,
        transcription_segments: list,
        diarization_segments: list,
    ) -> list:
        """
        Совместить сегменты транскрипции с диаризацией.

        Для каждого сегмента транскрипции определяет
        кто говорит (по максимальному пересечению времен).
        """
        for trans_seg in transcription_segments:
            # Найти перекрывающиеся сегменты диаризации
            overlaps = []
            for diar_seg in diarization_segments:
                overlap = self._calculate_overlap(trans_seg, diar_seg)
                if overlap > 0:
                    overlaps.append((diar_seg.speaker, overlap))

            # Выбрать говорящего с максимальным перекрытием
            if overlaps:
                trans_seg["speaker"] = max(overlaps, key=lambda x: x[1])[0]

        return transcription_segments
```

### Файл: `services/transcriber/postprocessor.py`

Постобработка текста:

```python
class Postprocessor:
    """
    Постобработка результатов транскрипции.

    Функции:
    - Восстановление пунктуации
    - Капитализация предложений
    - Форматирование в различные форматы (SRT, VTT, TXT)
    """

    def __init__(self, use_punctuation_model: bool = True):
        """
        Args:
            use_punctuation_model: Использовать ML модель для пунктуации
        """
        self.use_punctuation_model = use_punctuation_model
        self.punctuation_model = None

    def restore_punctuation(self, text: str) -> str:
        """
        Восстановить пунктуацию в тексте.

        Использует модель deepmultilingualpunctuation
        если доступна, иначе простые правила.
        """
        if self.use_punctuation_model:
            try:
                if self.punctuation_model is None:
                    from deepmultilingualpunctuation import PunctuationModel
                    self.punctuation_model = PunctuationModel()

                return self.punctuation_model.restore_punctuation(text)
            except Exception:
                pass

        # Fallback: простые правила
        return self._simple_punctuation(text)

    def _simple_punctuation(self, text: str) -> str:
        """Простые правила пунктуации."""
        # Капитализация первой буквы
        if text:
            text = text[0].upper() + text[1:]

        # Точка в конце если нет пунктуации
        if text and text[-1] not in ".!?":
            text += "."

        return text

    def format_output(
        self,
        segments: list,
        format: str = "json",
        include_speakers: bool = False,
    ) -> str:
        """
        Форматировать результат в нужный формат.

        Форматы:
        - json: Структурированный JSON
        - srt: Субтитры для видео (HH:MM:SS,mmm)
        - vtt: WebVTT субтитры (HH:MM:SS.mmm)
        - txt: Простой текст
        """
        if format == "json":
            return json.dumps([s.__dict__ for s in segments], indent=2)

        elif format == "srt":
            return self._format_srt(segments, include_speakers)

        elif format == "vtt":
            return self._format_vtt(segments, include_speakers)

        elif format == "txt":
            return self._format_txt(segments, include_speakers)

        else:
            raise ValueError(f"Неизвестный формат: {format}")

    def _format_srt(self, segments: list, include_speakers: bool) -> str:
        """
        Формат SRT (SubRip).

        Пример:
        1
        00:00:00,000 --> 00:00:05,200
        Hello world.

        2
        00:00:05,500 --> 00:00:10,300
        This is a test.
        """
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp_srt(seg.start)
            end = self._format_timestamp_srt(seg.end)
            text = seg.text
            if include_speakers and seg.speaker:
                text = f"[{seg.speaker}] {text}"

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def _format_timestamp_srt(self, seconds: float) -> str:
        """Конвертировать секунды в формат SRT (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
```

---

## 9. Frontend (Streamlit)

### Файл: `services/frontend/app.py`

Веб-интерфейс на Streamlit:

```python
import streamlit as st
import requests

# Конфигурация страницы
st.set_page_config(
    page_title="Speech-to-Text Pipeline",
    page_icon="🎤",
    layout="wide",
)

# API настройки
API_URL = os.environ.get("API_URL", "http://api:8000")
API_KEY = os.environ.get("API_KEY", "dev-api-key")

def main():
    """Главная функция приложения."""

    # Sidebar - навигация и настройки
    with st.sidebar:
        st.title("🎤 Speech-to-Text")

        # Выбор страницы
        page = st.radio(
            "Навигация",
            ["🎤 Transcribe", "📋 History", "📊 Dashboard", "⚙️ Settings"]
        )

        st.divider()

        # Настройки модели
        st.subheader("⚙️ Настройки")

        model_size = st.select_slider(
            "Качество модели",
            options=["tiny", "base", "small", "medium"],
            value="tiny",
            help="Больше = лучше качество, но медленнее"
        )

        # Расширенные настройки
        with st.expander("Расширенные настройки"):
            enable_diarization = st.toggle(
                "Определять говорящих",
                value=False,
                help="Идентифицировать разных говорящих"
            )

            if enable_diarization:
                min_speakers = st.number_input("Мин. говорящих", 1, 20, 1)
                max_speakers = st.number_input("Макс. говорящих", 1, 20, 5)

            output_format = st.selectbox(
                "Формат вывода",
                ["json", "srt", "vtt", "txt"]
            )

            language = st.selectbox(
                "Язык",
                ["Auto-detect", "en", "ru", "de", "es", "fr", "zh", "ja"],
                help="Язык аудио"
            )

    # Основной контент
    if page == "🎤 Transcribe":
        transcribe_page(model_size, enable_diarization, ...)
    elif page == "📋 History":
        history_page()
    elif page == "📊 Dashboard":
        dashboard_page()
    elif page == "⚙️ Settings":
        settings_page()

def transcribe_page(model_size, enable_diarization, ...):
    """Страница транскрипции."""

    st.header("🎤 Транскрипция аудио")

    col1, col2 = st.columns([2, 1])

    with col1:
        # Загрузка файла
        uploaded_file = st.file_uploader(
            "Загрузите аудио файл",
            type=["mp3", "wav", "flac", "ogg", "m4a", "webm"],
            help="Максимум 500MB"
        )

        if uploaded_file:
            # Показать информацию о файле
            st.info(f"📁 {uploaded_file.name} ({uploaded_file.size / 1024 / 1024:.1f} MB)")

            # Аудио плеер
            st.audio(uploaded_file)

            # Кнопка транскрипции
            if st.button("🚀 Начать транскрипцию", type="primary"):
                with st.spinner("Загрузка..."):
                    job_id = submit_transcription(
                        uploaded_file,
                        model_size,
                        enable_diarization,
                        ...
                    )

                if job_id:
                    st.session_state.current_job = job_id
                    st.rerun()

        # Отображение прогресса если есть активная задача
        if "current_job" in st.session_state:
            show_progress(st.session_state.current_job)

    with col2:
        # Советы
        st.markdown("""
        ### 💡 Советы

        - **Tiny** - быстро, базовое качество
        - **Small** - хороший баланс
        - **Medium** - высокое качество

        ### 📊 Скорость

        | Модель | 1 мин аудио |
        |--------|-------------|
        | Tiny   | ~3 сек      |
        | Small  | ~9 сек      |
        | Medium | ~18 сек     |
        """)

def submit_transcription(file, model_size, ...):
    """Отправить файл на транскрипцию."""

    response = requests.post(
        f"{API_URL}/transcribe/file",
        headers={"X-API-Key": API_KEY},
        files={"file": (file.name, file.getvalue())},
        data={
            "model_size": model_size,
            "enable_diarization": str(enable_diarization).lower(),
            "output_format": output_format,
            "language": language if language != "Auto-detect" else "",
        }
    )

    if response.ok:
        return response.json()["job_id"]
    else:
        st.error(f"Ошибка: {response.text}")
        return None

def show_progress(job_id):
    """Показать прогресс транскрипции."""

    progress_bar = st.progress(0)
    status_text = st.empty()

    while True:
        # Получить статус
        response = requests.get(
            f"{API_URL}/jobs/{job_id}",
            headers={"X-API-Key": API_KEY}
        )
        status = response.json()

        # Обновить прогресс
        progress_bar.progress(status["progress"] / 100)
        status_text.text(f"Статус: {status['current_step']} ({status['progress']}%)")

        # Проверить завершение
        if status["status"] == "completed":
            st.success("✅ Транскрипция завершена!")
            show_result(job_id)
            break
        elif status["status"] == "failed":
            st.error(f"❌ Ошибка: {status['error']}")
            break

        time.sleep(2)

def show_result(job_id):
    """Показать результат транскрипции."""

    response = requests.get(
        f"{API_URL}/jobs/{job_id}/result",
        headers={"X-API-Key": API_KEY}
    )
    result = response.json()

    # Метаданные
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🌐 Язык", result["metadata"]["language"].upper())
    col2.metric("⏱️ Длительность", f"{result['metadata']['duration']:.1f}с")
    col3.metric("🔄 Обработка", f"{result['metadata']['processing_time']:.1f}с")
    col4.metric("🤖 Модель", result["metadata"]["model_used"])

    # Полный текст
    st.subheader("📝 Транскрипция")
    st.text_area("", result["text"], height=200)

    # Сегменты с таймкодами
    if result["segments"]:
        st.subheader("📋 Сегменты")
        for seg in result["segments"][:50]:  # Первые 50
            speaker = f"[{seg.get('speaker', '')}] " if seg.get('speaker') else ""
            st.markdown(f"**{seg['start']:.1f}s - {seg['end']:.1f}s:** {speaker}{seg['text']}")

    # Кнопки скачивания
    st.subheader("📥 Скачать")
    col1, col2, col3, col4 = st.columns(4)
    col1.download_button("JSON", json.dumps(result, indent=2), "transcription.json")
    col2.download_button("TXT", result["text"], "transcription.txt")
    # ... SRT, VTT кнопки
```

### Стилизация

```python
# Кастомный CSS для темной темы
st.markdown("""
<style>
    /* Темный фон */
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    }

    /* Карточки с эффектом стекла */
    .card {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 10px;
        padding: 20px;
    }

    /* Градиентные кнопки */
    .stButton > button {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
    }

    /* Прогресс бар */
    .stProgress > div > div {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    }
</style>
""", unsafe_allow_html=True)
```

---

## 10. База данных (PostgreSQL)

### Схема базы данных

```sql
-- Расширение для UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enum для статусов
CREATE TYPE job_status AS ENUM (
    'queued',     -- В очереди
    'processing', -- Обрабатывается
    'completed',  -- Завершено
    'failed',     -- Ошибка
    'cancelled'   -- Отменено
);

-- Главная таблица задач
CREATE TABLE transcription_jobs (
    -- Идентификация
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Статус и прогресс
    status job_status NOT NULL DEFAULT 'queued',
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    current_step VARCHAR(50),
    error_message TEXT,

    -- Информация об аудио
    audio_path VARCHAR(500) NOT NULL,
    audio_format VARCHAR(20),
    audio_duration FLOAT,
    file_size BIGINT,

    -- Параметры транскрипции
    model_size VARCHAR(20) DEFAULT 'tiny',
    language VARCHAR(10),
    enable_diarization VARCHAR(10) DEFAULT 'false',
    min_speakers INTEGER DEFAULT 1,
    max_speakers INTEGER,
    output_format VARCHAR(20) DEFAULT 'json',
    enable_timestamps VARCHAR(10) DEFAULT 'true',
    enable_punctuation VARCHAR(10) DEFAULT 'true',

    -- Результаты
    result_path VARCHAR(500),
    result_text TEXT,
    detected_language VARCHAR(10),
    speakers_count INTEGER,
    processing_time FLOAT,

    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Безопасность
    api_key_hash VARCHAR(64)
);

-- Индексы для оптимизации
CREATE INDEX idx_jobs_status ON transcription_jobs(status);
CREATE INDEX idx_jobs_created_at ON transcription_jobs(created_at DESC);
CREATE INDEX idx_jobs_api_key ON transcription_jobs(api_key_hash);
```

### ORM модель (SQLAlchemy)

```python
# services/common/database.py

from sqlalchemy import Column, String, Integer, Float, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()

class JobStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    # UUID первичный ключ
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Статус - использует PostgreSQL ENUM
    status = Column(
        SQLEnum(JobStatus, name='job_status', create_type=False,
                values_callable=lambda obj: [e.value for e in obj]),
        default=JobStatus.QUEUED,
        nullable=False
    )

    # Прогресс 0-100
    progress = Column(Integer, default=0)
    current_step = Column(String(50))

    # Информация об аудио
    audio_path = Column(String(500), nullable=False)
    audio_duration = Column(Float)

    # Параметры
    model_size = Column(String(20), default="tiny")
    language = Column(String(10))

    # Результаты
    result_path = Column(String(500))
    result_text = Column(String)
    detected_language = Column(String(10))
    processing_time = Column(Float)

    # Временные метки
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # API ключ (хэшированный)
    api_key_hash = Column(String(64))
```

### Функции работы с БД

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Создание engine с connection pool
engine = create_engine(
    settings.database_url,
    pool_size=10,           # Постоянные соединения
    max_overflow=20,        # Дополнительные при нагрузке
    pool_pre_ping=True,     # Проверка соединения
)

SessionLocal = sessionmaker(bind=engine)

def init_db():
    """Создать все таблицы."""
    Base.metadata.create_all(bind=engine)

def get_db_session():
    """Получить сессию БД."""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

# FastAPI dependency
def get_db():
    """Generator для FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 11. Очередь задач (Redis + Celery)

### Как работает Celery

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     API     │     │    Redis    │     │   Worker    │
│             │     │   (Broker)  │     │  (Celery)   │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       │  1. Send task     │                   │
       │──────────────────▶│                   │
       │                   │                   │
       │                   │  2. Get task      │
       │                   │◀──────────────────│
       │                   │                   │
       │                   │  3. Execute       │
       │                   │                   │
       │                   │  4. Store result  │
       │                   │◀──────────────────│
       │                   │                   │
       │  5. Get result    │                   │
       │──────────────────▶│                   │
       │  6. Return result │                   │
       │◀──────────────────│                   │
```

### Конфигурация Redis

```yaml
# docker-compose.yml
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --maxmemory 256mb
    --maxmemory-policy allkeys-lru
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

**Параметры:**
- `maxmemory 256mb` - Максимум 256MB памяти
- `allkeys-lru` - При заполнении удалять старые ключи

### Отправка задачи

```python
# В API при загрузке файла
from worker.tasks import transcribe_audio

# Отправка задачи в очередь
task = transcribe_audio.delay(
    job_id="550e8400-...",
    audio_path="uploads/550e8400-.../audio.mp3",
    options={
        "model_size": "medium",
        "language": "ru",
        "enable_diarization": True,
    }
)

# task.id - ID задачи в Celery
# task.state - статус (PENDING, STARTED, SUCCESS, FAILURE)
```

### Получение результата

```python
# Синхронно (блокирует)
result = task.get(timeout=3600)

# Асинхронно (не блокирует)
if task.ready():
    result = task.result
```

### Мониторинг очереди

```bash
# Просмотр очереди
redis-cli LRANGE transcription 0 -1

# Количество задач в очереди
redis-cli LLEN transcription

# Активные воркеры
celery -A celery_app inspect active

# Статистика
celery -A celery_app inspect stats
```

---

## 12. Хранилище файлов (MinIO)

### Что такое MinIO

MinIO - это S3-совместимое объектное хранилище:
- Хранит файлы (аудио, результаты)
- Работает через HTTP API
- Совместимо с AWS S3

### Структура хранилища

```
stt-audio/                          # Bucket
├── uploads/                        # Загруженные файлы
│   ├── {job_id}/
│   │   └── audio.mp3
│   └── {job_id}/
│       └── audio.wav
│
└── results/                        # Результаты
    ├── {job_id}/
    │   └── transcription.json
    └── {job_id}/
        └── transcription.json
```

### Клиент MinIO

```python
# services/common/storage.py

from minio import Minio
from tenacity import retry, stop_after_attempt, wait_exponential

class StorageClient:
    """
    Клиент для работы с MinIO/S3.

    Использует tenacity для автоматических повторов
    при сетевых ошибках.
    """

    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,      # minio:9000
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,  # False для локальной разработки
        )

        # Создать bucket если не существует
        if not self.client.bucket_exists(settings.minio_bucket):
            self.client.make_bucket(settings.minio_bucket)

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, max=10))
    def upload_bytes(self, data: bytes, object_name: str, content_type: str):
        """
        Загрузить bytes в MinIO.

        @retry - автоматически повторить до 3 раз при ошибке
        """
        from io import BytesIO

        self.client.put_object(
            settings.minio_bucket,
            object_name,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

        return f"s3://{settings.minio_bucket}/{object_name}"

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, max=10))
    def download_file(self, object_name: str, local_path: str):
        """Скачать файл из MinIO на диск."""
        self.client.fget_object(
            settings.minio_bucket,
            object_name,
            local_path,
        )
        return local_path

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, max=10))
    def get_file_bytes(self, object_name: str) -> bytes:
        """Получить содержимое файла в память."""
        response = self.client.get_object(
            settings.minio_bucket,
            object_name,
        )
        return response.read()

    def get_presigned_url(self, object_name: str, expires_hours: int = 24) -> str:
        """
        Получить подписанный URL для скачивания.

        URL работает без авторизации в течение указанного времени.
        """
        from datetime import timedelta

        return self.client.presigned_get_object(
            settings.minio_bucket,
            object_name,
            expires=timedelta(hours=expires_hours),
        )

# Singleton
_storage = None

def get_storage() -> StorageClient:
    global _storage
    if _storage is None:
        _storage = StorageClient()
    return _storage
```

### Доступ к MinIO Console

```
URL: http://localhost:9001
Login: minioadmin
Password: minioadmin
```

---

## 13. Мониторинг (Prometheus + Grafana)

### Prometheus метрики

```python
# services/common/metrics.py

from prometheus_client import Counter, Histogram, Gauge, Info

# Счетчики (только растут)
transcription_requests_total = Counter(
    "stt_transcription_requests_total",
    "Общее количество запросов транскрипции",
    ["status", "model_size", "format"]
)

# Использование:
transcription_requests_total.labels(
    status="completed",
    model_size="medium",
    format="mp3"
).inc()

# Гистограммы (распределение значений)
transcription_duration_seconds = Histogram(
    "stt_transcription_duration_seconds",
    "Время транскрипции в секундах",
    ["model_size", "enable_diarization"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600]
)

# Использование:
transcription_duration_seconds.labels(
    model_size="medium",
    enable_diarization="false"
).observe(45.2)  # 45.2 секунды

# Gauge (текущее значение)
active_jobs = Gauge(
    "stt_active_jobs",
    "Количество активных задач"
)

# Использование:
active_jobs.inc()   # +1
active_jobs.dec()   # -1
active_jobs.set(5)  # установить 5

# Info (статическая информация)
app_info = Info(
    "stt_app",
    "Информация о приложении"
)

app_info.info({
    "version": "1.0.0",
    "model_default": "tiny",
    "environment": "production"
})
```

### Endpoint /metrics

```
GET http://localhost:8000/metrics

# HELP stt_transcription_requests_total Total transcription requests
# TYPE stt_transcription_requests_total counter
stt_transcription_requests_total{format="mp3",model_size="medium",status="completed"} 42.0
stt_transcription_requests_total{format="wav",model_size="tiny",status="failed"} 3.0

# HELP stt_transcription_duration_seconds Transcription duration
# TYPE stt_transcription_duration_seconds histogram
stt_transcription_duration_seconds_bucket{le="1.0",model_size="tiny"} 5.0
stt_transcription_duration_seconds_bucket{le="5.0",model_size="tiny"} 15.0
...

# HELP stt_active_jobs Current active jobs
# TYPE stt_active_jobs gauge
stt_active_jobs 2.0
```

### Grafana дашборды

```yaml
# monitoring/grafana/dashboards/overview.json

# Примеры панелей:

1. Requests per second:
   rate(stt_transcription_requests_total[5m])

2. Error rate:
   rate(stt_transcription_requests_total{status="failed"}[5m])
   / rate(stt_transcription_requests_total[5m])

3. Average processing time:
   rate(stt_transcription_duration_seconds_sum[5m])
   / rate(stt_transcription_duration_seconds_count[5m])

4. Queue depth:
   stt_jobs_queue_size{status="queued"}

5. GPU memory usage:
   stt_gpu_memory_usage_bytes
```

### Доступ к Grafana

```
URL: http://localhost:3000
Login: admin
Password: admin (по умолчанию)
```

---

## 14. Docker конфигурация

### docker-compose.yml (основной)

```yaml
services:
  # API сервис
  api:
    build:
      context: ./services/api
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://stt:stt@postgres:5432/stt
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
      - API_KEY=${API_KEY:-dev-api-key}
    volumes:
      - ./services/common:/app/common
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 1G

  # Worker сервис
  worker:
    build:
      context: ./services/worker
      dockerfile: Dockerfile
    environment:
      - DATABASE_URL=postgresql://stt:stt@postgres:5432/stt
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
      - MODEL_CACHE_DIR=/models
      - DEFAULT_MODEL_SIZE=${DEFAULT_MODEL_SIZE:-tiny}
    volumes:
      - ./models:/models              # Модели Whisper
      - ./services/common:/app/common
      - ./services/transcriber:/app/transcriber
      - audio_temp:/tmp/audio
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 10G

  # Frontend
  frontend:
    build:
      context: ./services/frontend
      dockerfile: Dockerfile
    ports:
      - "8501:8501"
    environment:
      - API_URL=http://api:8000
      - API_KEY=${API_KEY:-dev-api-key}
    depends_on:
      - api
    deploy:
      resources:
        limits:
          memory: 512M

  # PostgreSQL
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=stt
      - POSTGRES_PASSWORD=stt
      - POSTGRES_DB=stt
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U stt"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M

  # Redis
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M

  # MinIO
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M

  # Prometheus
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=15d'
    deploy:
      resources:
        limits:
          memory: 512M

  # Grafana
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana:/etc/grafana/provisioning
    depends_on:
      - prometheus
    deploy:
      resources:
        limits:
          memory: 256M

volumes:
  redis_data:
  postgres_data:
  minio_data:
  prometheus_data:
  grafana_data:
  audio_temp:

networks:
  default:
    name: stt-network
```

### Dockerfile для API

```dockerfile
# services/api/Dockerfile

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Переменные окружения
ENV UV_SYSTEM_PYTHON=1
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Код приложения
COPY . .

# Пользователь без root прав
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Запуск
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Dockerfile для Worker (CPU)

```dockerfile
# services/worker/Dockerfile

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_SYSTEM_PYTHON=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_HTTP_TIMEOUT=300
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Системные зависимости (включая ffmpeg для аудио)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU версия
RUN uv pip install \
    torch==2.5.1+cpu \
    torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Остальные зависимости
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Код
COPY . .

# Папки для моделей
RUN mkdir -p /models /tmp/audio

# Пользователь
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /models /tmp/audio
USER appuser

# Запуск Celery
CMD ["celery", "-A", "celery_app", "worker", "-l", "INFO", "-Q", "transcription"]
```

---

## 15. Библиотеки и зависимости

### API (services/api/requirements.txt)

```
# Web framework
fastapi==0.109.0          # Асинхронный web framework
uvicorn==0.27.0           # ASGI сервер
python-multipart==0.0.6   # Загрузка файлов

# Database
sqlalchemy==2.0.25        # ORM
psycopg2-binary==2.9.9    # PostgreSQL драйвер
alembic==1.13.1           # Миграции БД

# Validation
pydantic==2.5.3           # Валидация данных
pydantic-settings==2.1.0  # Конфигурация из env

# Task queue
celery==5.3.6             # Очередь задач
redis==5.0.1              # Redis клиент

# Storage
minio==7.2.3              # S3 клиент
tenacity==8.2.3           # Retry логика

# Monitoring
prometheus-client==0.19.0 # Метрики

# Rate limiting
slowapi==0.1.9            # Rate limiter

# Utilities
python-dotenv==1.0.0      # .env файлы
```

### Worker (services/worker/requirements.txt)

```
# ML Framework
torch==2.5.1              # PyTorch (версия без CUDA суффикса)
torchaudio==2.5.1         # Аудио обработка

# Speech-to-Text
faster-whisper==1.1.0     # Оптимизированный Whisper
ctranslate2==4.5.0        # C++ inference engine

# Audio processing
librosa==0.10.1           # Аудио анализ
soundfile==0.12.1         # Чтение/запись аудио
numpy==1.26.3             # Численные операции

# Speaker diarization (опционально)
pyannote.audio==3.1.0     # Диаризация
speechbrain==0.5.16       # ML для речи

# Punctuation
deepmultilingualpunctuation==1.0.1  # Восстановление пунктуации

# Task queue
celery==5.3.6             # Очередь задач
redis==5.0.1              # Redis клиент

# Database
sqlalchemy==2.0.25        # ORM
psycopg2-binary==2.9.9    # PostgreSQL

# Storage
minio==7.2.3              # S3 клиент
tenacity==8.2.3           # Retry

# Monitoring
prometheus-client==0.19.0 # Метрики

# HuggingFace
huggingface-hub==0.20.2   # Скачивание моделей
transformers==4.36.2      # ML модели
```

### Frontend (services/frontend/requirements.txt)

```
# UI Framework
streamlit==1.31.0         # Web интерфейс

# HTTP client
requests==2.31.0          # HTTP запросы

# Utilities
python-dotenv==1.0.0      # .env файлы
```

### Описание ключевых библиотек

| Библиотека | Назначение |
|------------|-----------|
| **FastAPI** | Асинхронный REST API framework с автодокументацией |
| **Celery** | Распределенная очередь задач |
| **SQLAlchemy** | ORM для работы с PostgreSQL |
| **Faster-Whisper** | Оптимизированная версия OpenAI Whisper (2-4x быстрее) |
| **pyannote.audio** | Определение говорящих (speaker diarization) |
| **librosa** | Загрузка и обработка аудио файлов |
| **Streamlit** | Быстрое создание web интерфейсов |
| **MinIO** | S3-совместимое объектное хранилище |
| **Prometheus** | Сбор и хранение метрик |

---

## 16. Примеры использования API

### cURL примеры

```bash
# 1. Проверка здоровья API
curl http://localhost:8000/health

# 2. Загрузка и транскрипция файла
curl -X POST "http://localhost:8000/transcribe/file" \
  -H "X-API-Key: dev-api-key" \
  -F "file=@audio.mp3" \
  -F "model_size=small" \
  -F "language=ru"

# 3. Проверка статуса задачи
curl -H "X-API-Key: dev-api-key" \
  "http://localhost:8000/jobs/{job_id}"

# 4. Получение результата
curl -H "X-API-Key: dev-api-key" \
  "http://localhost:8000/jobs/{job_id}/result"

# 5. Список задач
curl -H "X-API-Key: dev-api-key" \
  "http://localhost:8000/jobs?status=completed&limit=10"

# 6. Отмена задачи
curl -X DELETE -H "X-API-Key: dev-api-key" \
  "http://localhost:8000/jobs/{job_id}"
```

### Python пример

```python
import requests
import time

API_URL = "http://localhost:8000"
API_KEY = "dev-api-key"
HEADERS = {"X-API-Key": API_KEY}

def transcribe_file(filepath, model_size="small", language=None):
    """
    Полный пример транскрипции файла.
    """

    # 1. Загрузка файла
    print(f"Загрузка {filepath}...")
    with open(filepath, "rb") as f:
        response = requests.post(
            f"{API_URL}/transcribe/file",
            headers=HEADERS,
            files={"file": f},
            data={
                "model_size": model_size,
                "language": language or "",
                "enable_diarization": "false",
                "output_format": "json",
            }
        )

    if not response.ok:
        print(f"Ошибка: {response.text}")
        return None

    job_id = response.json()["job_id"]
    print(f"Задача создана: {job_id}")

    # 2. Ожидание завершения
    while True:
        status_response = requests.get(
            f"{API_URL}/jobs/{job_id}",
            headers=HEADERS
        )
        status = status_response.json()

        print(f"  {status['current_step']}: {status['progress']}%")

        if status["status"] == "completed":
            break
        elif status["status"] == "failed":
            print(f"Ошибка: {status['error']}")
            return None

        time.sleep(2)

    # 3. Получение результата
    result_response = requests.get(
        f"{API_URL}/jobs/{job_id}/result",
        headers=HEADERS
    )
    result = result_response.json()

    print(f"\n=== Результат ===")
    print(f"Язык: {result['metadata']['language']}")
    print(f"Длительность: {result['metadata']['duration']:.1f}с")
    print(f"Обработка: {result['metadata']['processing_time']:.1f}с")
    print(f"\nТекст:\n{result['text']}")

    return result

# Использование
if __name__ == "__main__":
    result = transcribe_file(
        "audio.mp3",
        model_size="small",
        language="ru"
    )
```

---

## 17. Устранение неполадок

### Частые проблемы

#### 1. Ошибка "Model not found"

```
Проблема: Модель Whisper не скачана

Решение:
make download-model-tiny
# или
make download-model-small
```

#### 2. Ошибка "Out of memory"

```
Проблема: Недостаточно памяти для модели

Решение:
1. Использовать меньшую модель (tiny вместо medium)
2. Увеличить memory limit в docker-compose.yml
3. Закрыть другие приложения
```

#### 3. Задача зависла в статусе "queued"

```
Проблема: Worker не обрабатывает задачи

Диагностика:
docker-compose logs worker

Решение:
docker-compose restart worker
```

#### 4. Ошибка "Connection refused" к API

```
Проблема: API не запущен или не готов

Диагностика:
curl http://localhost:8000/health

Решение:
docker-compose up -d api
docker-compose logs api
```

#### 5. Медленная транскрипция

```
Проблема: Обработка занимает слишком много времени

Решение:
1. Использовать GPU (make gpu)
2. Использовать меньшую модель
3. Отключить диаризацию
```

### Полезные команды для отладки

```bash
# Логи всех сервисов
make logs

# Логи конкретного сервиса
docker-compose logs api
docker-compose logs worker
docker-compose logs frontend

# Статус сервисов
make status

# Перезапуск
docker-compose restart

# Shell в контейнере
make shell-worker
make shell-api

# PostgreSQL консоль
make db-shell

# Проверка Redis
docker-compose exec redis redis-cli ping

# Очистка очереди задач
docker-compose exec redis redis-cli FLUSHALL
```

### Проверка компонентов

```bash
# API
curl http://localhost:8000/health

# Frontend
curl -I http://localhost:8501

# Redis
docker-compose exec redis redis-cli ping

# PostgreSQL
docker-compose exec postgres pg_isready -U stt

# MinIO
curl http://localhost:9000/minio/health/live
```

---

## Заключение

Speech-to-Text Pipeline - это полноценная система для транскрипции аудио, построенная на современных технологиях:

- **FastAPI** для быстрого REST API
- **Celery + Redis** для фоновой обработки
- **Faster-Whisper** для качественной транскрипции
- **pyannote.audio** для определения говорящих
- **Streamlit** для удобного интерфейса
- **Docker Compose** для простого развертывания

Система поддерживает 99+ языков, различные форматы аудио и вывода, масштабируется как вертикально (GPU), так и горизонтально (несколько воркеров).

---

*Документация создана для версии 1.0.0*
