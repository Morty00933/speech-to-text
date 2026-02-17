"""
Celery application configuration.
"""
from celery import Celery

from common.config import settings

# Create Celery app
app = Celery("stt_worker")

# Configure Celery
app.conf.update(
    # Broker settings
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,

    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_track_started=True,
    task_time_limit=settings.task_time_limit,
    task_soft_time_limit=settings.task_time_limit - 60,
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time (GPU bound)
    worker_concurrency=settings.celery_concurrency,
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks to prevent memory leaks

    # Queue settings
    task_default_queue="transcription",
    task_queues={
        "transcription": {
            "exchange": "transcription",
            "routing_key": "transcription",
        },
    },

    # Result settings
    result_expires=86400,  # 24 hours

    # Retry settings
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Задачи регистрируются через autodiscover.
# celery_app.py и tasks.py оба копируются в /app/ через COPY worker/ .
# Поэтому модуль называется "tasks", задача регистрируется как "tasks.transcribe_audio".
# Используем autodiscover вместо прямого импорта чтобы избежать кругового импорта:
#   celery_app → tasks → celery_app (tasks.py делает `from celery_app import app`)
# При autodiscover Celery сам импортирует tasks после инициализации app.
app.autodiscover_tasks(["tasks"], force=True)
