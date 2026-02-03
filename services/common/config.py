"""
Configuration management for Speech-to-Text Pipeline.
Loads settings from environment variables with sensible defaults.
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    api_port: int = 8000
    api_key: str = "dev-api-key"
    # Additional API keys (comma-separated plain text). Optional.
    api_keys: str = ""
    # CORS allowed origins (comma-separated). Use "*" only for local dev without credentials.
    cors_origins: str = "http://localhost:8501,http://localhost:3000"
    rate_limit: str = "100/minute"
    max_file_size_mb: int = 500

    # Database
    postgres_user: str = "stt"
    postgres_password: str = "stt"
    postgres_db: str = "stt"
    database_url: str = "postgresql://stt:stt@postgres:5432/stt"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # MinIO/S3 Storage
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "stt-audio"
    minio_secure: bool = False

    # Models
    hf_token: Optional[str] = None
    model_cache_dir: str = "/models"
    default_model_size: str = "tiny"  # tiny для быстрого старта, medium/small для качества

    # Monitoring
    grafana_password: str = "admin"
    prometheus_port: int = 9090
    grafana_port: int = 3000

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # GPU
    cuda_visible_devices: str = "0"

    # Worker
    celery_concurrency: int = 1
    task_time_limit: int = 3600

    # JWT Authentication
    # Use a strong random secret in production: openssl rand -hex 32
    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Computed properties
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
