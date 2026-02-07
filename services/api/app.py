"""
Speech-to-Text Pipeline API
Main FastAPI application.
"""
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from common.config import settings
from common.logging_config import setup_logging, get_logger
from common.database import init_db
from common.metrics import (
    api_requests_total,
    api_request_duration_seconds,
    app_info,
)

from routes import health, transcribe, jobs, auth as auth_routes, ws as ws_routes

# Setup logging
setup_logging(settings.log_level, settings.log_format, "stt.api")
logger = get_logger("api")

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Speech-to-Text API...")

    # Initialize database — fatal: if DB is not available, refuse to start
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise RuntimeError(f"Cannot start API: database initialization failed: {e}") from e

    # Set app info metric
    app_info.info({
        "version": "1.0.0",
        "model_default": settings.default_model_size,
        "environment": "production" if settings.log_format == "json" else "development",
    })

    logger.info("Speech-to-Text API started successfully")
    yield

    # Shutdown
    logger.info("Shutting down Speech-to-Text API...")


# Create FastAPI app
app = FastAPI(
    title="Speech-to-Text Pipeline API",
    description="""
    Production-ready Speech-to-Text API with speaker diarization support.

    ## Features
    - High-quality transcription using Whisper
    - Speaker diarization (who said what)
    - Multiple output formats (JSON, SRT, VTT, TXT)
    - Batch processing
    - Real-time progress tracking

    ## Authentication
    All endpoints require an API key passed via the `X-API-Key` header.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
# allow_origins=["*"] with allow_credentials=True is invalid (browsers reject it).
# Origins are configured via CORS_ORIGINS env var (comma-separated list).
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Accept"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware for request metrics."""
    start_time = time.time()

    response = await call_next(request)

    # Skip metrics endpoint
    if request.url.path != "/metrics":
        duration = time.time() - start_time
        api_requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
        ).inc()
        api_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)

    return response


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Middleware for request logging."""
    start_time = time.time()

    response = await call_next(request)

    # Skip health checks in logs
    if request.url.path not in ["/health", "/health/live", "/health/ready", "/metrics"]:
        duration = time.time() - start_time
        logger.info(
            f"{request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": round(duration, 3),
            }
        )

    return response


# Include routers
app.include_router(health.router)
app.include_router(transcribe.router)
app.include_router(jobs.router)
app.include_router(auth_routes.router)
app.include_router(ws_routes.router)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Speech-to-Text Pipeline API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
