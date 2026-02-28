"""
Integration test fixtures.

Uses an in-process SQLite database and mocks for MinIO, Redis, and Celery
so that the tests run without any external services.
"""
import io
import uuid
from unittest.mock import MagicMock, patch
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ---------------------------------------------------------------------------
# Patch settings BEFORE importing the application so that every module that
# calls get_settings() or imports `settings` at module level uses test values.
# ---------------------------------------------------------------------------
TEST_API_KEY = "test-api-key-integration"
TEST_JWT_SECRET = "test-jwt-secret-for-integration-tests"

import sys
import os

# Add services/api and services to the Python path so that imports work
_here = os.path.dirname(__file__)
_root = os.path.abspath(os.path.join(_here, "..", ".."))
for _path in [
    os.path.join(_root, "services", "api"),
    os.path.join(_root, "services"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)


# Patch settings before any app import
from common import config as _cfg_module

_test_settings = _cfg_module.Settings(
    api_key=TEST_API_KEY,
    api_keys="",
    database_url="sqlite:///:memory:",
    redis_url="redis://localhost:6379/15",
    minio_endpoint="localhost:9000",
    minio_access_key="minioadmin",
    minio_secret_key="minioadmin",
    minio_bucket="test-bucket",
    jwt_secret_key=TEST_JWT_SECRET,
    jwt_expire_minutes=5,
    default_model_size="tiny",
    log_format="text",
    log_level="WARNING",
)

# Override the cached singleton
_cfg_module.get_settings.cache_clear()
with patch.object(_cfg_module, "settings", _test_settings):
    pass  # Just to clear cache; we monkey-patch below

# Hard-patch the module-level `settings` attribute used everywhere
_cfg_module.settings = _test_settings
import common.config
common.config.settings = _test_settings


# ---------------------------------------------------------------------------
# SQLite in-memory database setup
# ---------------------------------------------------------------------------
from common.database import Base

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(_engine)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _get_test_db() -> Generator[Session, None, None]:
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Application client fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """
    Provides a FastAPI TestClient with mocked external dependencies.

    Mocked:
      - PostgreSQL → SQLite in-memory (via db_session override)
      - MinIO → MagicMock (no real S3 calls)
      - Redis/Celery → no-op mocks
    """
    mock_storage = MagicMock()
    mock_storage.upload_bytes.return_value = None
    mock_storage.upload_file.return_value = None
    mock_storage.download_file.return_value = None
    mock_storage.get_file_bytes.return_value = b'{"text": "test", "segments": []}'
    mock_storage.delete_file.return_value = None

    mock_celery = MagicMock()
    mock_celery.send_task.return_value = MagicMock(id=str(uuid.uuid4()))

    with (
        patch("common.storage.get_storage", return_value=mock_storage),
        patch("common.celery_client.celery_app", mock_celery),
        patch("common.database.db_session") as mock_db_ctx,
        patch("routes.transcribe.get_storage", return_value=mock_storage),
        patch("routes.transcribe.celery_app", mock_celery),
        patch("routes.jobs.get_storage", return_value=mock_storage),
        patch("routes.health.get_storage", return_value=mock_storage),
    ):
        # Wire the db_session context manager to our in-memory SQLite
        from contextlib import contextmanager

        @contextmanager
        def _sqlite_session():
            db = _TestSessionLocal()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        mock_db_ctx.side_effect = _sqlite_session

        from app import app  # Import after all patches
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture
def valid_headers() -> dict:
    """Headers with a valid API key."""
    return {"X-API-Key": TEST_API_KEY}


@pytest.fixture
def invalid_headers() -> dict:
    """Headers with an invalid API key."""
    return {"X-API-Key": "wrong-key-xxxxx"}


@pytest.fixture
def valid_audio_bytes() -> bytes:
    """Minimal valid WAV file (44-byte header + silence)."""
    import struct
    # Minimal WAV: 44-byte header with 0 data samples
    num_channels = 1
    sample_rate = 16000
    bits_per_sample = 16
    data = b""
    data_size = len(data)
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,          # sub-chunk size
        1,           # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + data
