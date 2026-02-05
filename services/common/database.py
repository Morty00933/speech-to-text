"""
Database models and connection for Speech-to-Text Pipeline.
Uses SQLAlchemy with PostgreSQL.
"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from enum import Enum

from sqlalchemy import create_engine, Column, String, DateTime, Float, Integer, Text, Boolean, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.dialects.postgresql import UUID

from .config import settings

# Create engine
engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class JobStatus(str, Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscriptionJob(Base):
    """Transcription job model."""

    __tablename__ = "transcription_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(
        SQLEnum(
            JobStatus,
            name='job_status',
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj]
        ),
        default=JobStatus.QUEUED,
        nullable=False
    )

    # Input
    audio_path = Column(String(500), nullable=False)
    audio_format = Column(String(20))
    audio_duration = Column(Float)
    file_size = Column(Integer)

    # Options
    model_size = Column(String(20), default="medium")
    language = Column(String(10))
    enable_diarization = Column(Boolean, default=False)
    min_speakers = Column(Integer, default=1)
    max_speakers = Column(Integer)
    output_format = Column(String(10), default="json")
    enable_timestamps = Column(Boolean, default=True)
    enable_punctuation = Column(Boolean, default=True)

    # Result
    result_path = Column(String(500))
    result_text = Column(Text)
    detected_language = Column(String(10))
    speakers_count = Column(Integer)

    # Metadata
    processing_time = Column(Float)
    error_message = Column(Text)
    progress = Column(Integer, default=0)
    current_step = Column(String(50))

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # API Key tracking
    api_key_hash = Column(String(64))


def init_db():
    """Initialize database tables and required PostgreSQL types."""
    from sqlalchemy import text as sa_text
    with engine.connect() as conn:
        conn.execute(sa_text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
                    CREATE TYPE job_status AS ENUM (
                        'queued', 'processing', 'completed', 'failed', 'cancelled'
                    );
                END IF;
            END
            $$;
        """))
        conn.commit()
    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session() -> Session:
    """Context manager for database sessions.

    Usage::

        with db_session() as db:
            job = db.query(TranscriptionJob).filter(...).first()
            job.status = JobStatus.COMPLETED
            db.commit()

    The session is automatically closed when the block exits.
    Callers are responsible for calling ``db.commit()`` when writes are needed.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
