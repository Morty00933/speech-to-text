"""
Shared Celery client for API layer (task submission and revocation).

This is the single Celery client instance used by all API routes.
The worker has its own Celery app defined in celery_app.py.
"""
from celery import Celery

from .config import settings

celery_app = Celery(
    "stt_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
