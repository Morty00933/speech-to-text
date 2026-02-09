"""
Health check endpoints.
"""
import time
from typing import List
from fastapi import APIRouter, Response
import redis
from sqlalchemy import text

from common.config import settings
from common.database import engine
from schemas import HealthResponse, ServiceHealth

router = APIRouter(tags=["Health"])

VERSION = "1.0.0"


def check_postgres() -> ServiceHealth:
    """Check PostgreSQL connection."""
    start = time.time()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = (time.time() - start) * 1000
        return ServiceHealth(name="postgres", status="healthy", latency_ms=latency)
    except Exception as e:
        return ServiceHealth(name="postgres", status="unhealthy", error=str(e))


def check_redis() -> ServiceHealth:
    """Check Redis connection."""
    start = time.time()
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        latency = (time.time() - start) * 1000
        return ServiceHealth(name="redis", status="healthy", latency_ms=latency)
    except Exception as e:
        return ServiceHealth(name="redis", status="unhealthy", error=str(e))


def check_minio() -> ServiceHealth:
    """Check MinIO connection."""
    start = time.time()
    try:
        from minio import Minio
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        client.bucket_exists(settings.minio_bucket)
        latency = (time.time() - start) * 1000
        return ServiceHealth(name="minio", status="healthy", latency_ms=latency)
    except Exception as e:
        return ServiceHealth(name="minio", status="unhealthy", error=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response):
    """
    Check the health of all services.

    Returns:
        Health status of API and all dependent services
    """
    services: List[ServiceHealth] = [
        check_postgres(),
        check_redis(),
        check_minio(),
    ]

    # Determine overall status
    all_healthy = all(s.status == "healthy" for s in services)
    overall_status = "healthy" if all_healthy else "degraded"

    if not all_healthy:
        response.status_code = 503

    return HealthResponse(
        status=overall_status,
        version=VERSION,
        services=services
    )


@router.get("/health/live")
async def liveness_check():
    """
    Kubernetes liveness probe.
    Returns 200 if the service is running.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness_check(response: Response):
    """
    Kubernetes readiness probe.
    Returns 200 if the service is ready to accept traffic.
    """
    # Check critical dependencies
    pg_health = check_postgres()
    redis_health = check_redis()

    if pg_health.status != "healthy" or redis_health.status != "healthy":
        response.status_code = 503
        return {"status": "not ready", "reason": "Dependencies not healthy"}

    return {"status": "ready"}
