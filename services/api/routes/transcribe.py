"""
Transcription endpoints.
"""
import os
import uuid
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException

from common.config import settings
from common.logging_config import get_logger
from common.storage import get_storage
from common.database import db_session, TranscriptionJob, JobStatus as DBJobStatus
from common.celery_client import celery_app
from common.metrics import transcription_requests_total
from auth import verify_api_key, get_api_key_hash
from schemas import (
    TranscribeOptions,
    TranscribeResponse,
    TranscribeURLRequest,
    BatchTranscribeRequest,
    BatchJobResponse,
    BatchJobFailure,
    JobStatus,
    ModelSize,
    OutputFormat,
)

logger = get_logger("transcribe")
router = APIRouter(prefix="/transcribe", tags=["Transcription"])

# Allowed audio formats (MIME type → file extension)
# OGG, M4A, and OPUS are handled by ffmpeg conversion in the preprocessor
ALLOWED_FORMATS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "audio/m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    # OPUS formats — converted via ffmpeg in preprocessor
    "audio/opus": "opus",
    "audio/x-opus": "opus",
    "audio/ogg; codecs=opus": "opus",
}


def _is_internal_url(url: str) -> bool:
    """Check if URL points to internal/private network (SSRF protection)."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True

    if hostname.lower() in {"localhost", "0.0.0.0"}:
        return True

    # Check if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass

    # Resolve hostname and check resolved IPs
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except socket.gaierror:
        return True  # Cannot resolve — block for safety

    return False


def validate_audio_file(file: UploadFile) -> str:
    """Validate uploaded audio file and return format."""
    content_type = file.content_type or ""
    if content_type not in ALLOWED_FORMATS:
        ext = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
        if ext not in ALLOWED_FORMATS.values():
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audio format. Allowed: {list(set(ALLOWED_FORMATS.values()))}"
            )
        return ext
    return ALLOWED_FORMATS[content_type]


async def save_uploaded_file(file: UploadFile, job_id: str, audio_format: str) -> tuple[str, int]:
    """Save uploaded file to storage and return (object_name, file_size)."""
    storage = get_storage()

    content = await file.read()
    file_size = len(content)

    if file_size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB"
        )

    object_name = f"uploads/{job_id}/audio.{audio_format}"
    storage.upload_bytes(content, object_name, content_type=file.content_type or "audio/mpeg")

    return object_name, file_size


def create_job(
    audio_path: str,
    audio_format: str,
    file_size: int,
    options: TranscribeOptions,
    api_key_hash: str,
) -> TranscriptionJob:
    """Create a new transcription job in the database."""
    with db_session() as db:
        job = TranscriptionJob(
            audio_path=audio_path,
            audio_format=audio_format,
            file_size=file_size,
            model_size=options.model_size.value,
            language=options.language,
            enable_diarization=options.enable_diarization,
            min_speakers=options.min_speakers,
            max_speakers=options.max_speakers,
            output_format=options.output_format.value,
            enable_timestamps=options.enable_timestamps,
            enable_punctuation=options.enable_punctuation,
            api_key_hash=api_key_hash,
            status=DBJobStatus.QUEUED,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        # Expunge so the object remains usable after session close
        db.expunge(job)
        return job


def submit_transcription_task(job: TranscriptionJob, options: TranscribeOptions):
    """Submit transcription task to Celery.

    We explicitly set ``task_id=str(job.id)`` so that the Celery task ID
    matches the database job ID.  This allows the cancel endpoint to revoke
    the correct task via ``celery_app.control.revoke(job_id, terminate=True)``
    without needing to store a separate celery_task_id column.
    """
    celery_app.send_task(
        "tasks.transcribe_audio",
        args=[
            str(job.id),
            job.audio_path,
            {
                "model_size": options.model_size.value,
                "language": options.language,
                "enable_diarization": options.enable_diarization,
                "min_speakers": options.min_speakers,
                "max_speakers": options.max_speakers,
                "output_format": options.output_format.value,
                "enable_timestamps": options.enable_timestamps,
                "enable_punctuation": options.enable_punctuation,
            }
        ],
        task_id=str(job.id),  # Celery task ID == job ID → revoke() works correctly
        queue="transcription",
    )


def delete_job(job_id: str):
    """Delete orphaned job from database (used on task submission failure)."""
    try:
        with db_session() as db:
            job = db.query(TranscriptionJob).filter(TranscriptionJob.id == job_id).first()
            if job:
                db.delete(job)
                db.commit()
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned job {job_id}: {e}")


@router.post("/file", response_model=TranscribeResponse)
async def transcribe_file(
    file: UploadFile = File(..., description="Audio file to transcribe"),
    language: Optional[str] = Form(None),
    model_size: ModelSize = Form(ModelSize.MEDIUM),
    enable_diarization: bool = Form(False),
    min_speakers: int = Form(1),
    max_speakers: Optional[int] = Form(None),
    output_format: OutputFormat = Form(OutputFormat.JSON),
    enable_timestamps: bool = Form(True),
    enable_punctuation: bool = Form(True),
    api_key: str = Depends(verify_api_key),
):
    """
    Upload and transcribe an audio file.

    Supported formats: MP3, WAV, FLAC, OGG, M4A, WebM
    Maximum file size: 500MB
    """
    job_id = str(uuid.uuid4())

    options = TranscribeOptions(
        language=language,
        model_size=model_size,
        enable_diarization=enable_diarization,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        output_format=output_format,
        enable_timestamps=enable_timestamps,
        enable_punctuation=enable_punctuation,
    )

    try:
        audio_format = validate_audio_file(file)
        audio_path, file_size = await save_uploaded_file(file, job_id, audio_format)

        key_hash = get_api_key_hash(api_key)
        job = create_job(audio_path, audio_format, file_size, options, key_hash)

        try:
            submit_transcription_task(job, options)
        except Exception as celery_exc:
            delete_job(str(job.id))
            logger.error(f"Failed to submit task to Celery (Redis unavailable?): {celery_exc}")
            raise HTTPException(
                status_code=503,
                detail="Task queue is unavailable. Please try again later.",
            )

        transcription_requests_total.labels(
            status="queued",
            model_size=model_size.value,
            format=audio_format,
        ).inc()

        logger.info(
            f"Created transcription job",
            extra={"job_id": str(job.id), "model": model_size.value}
        )

        return TranscribeResponse(
            job_id=str(job.id),
            status=JobStatus.QUEUED,
            created_at=job.created_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Failed to create transcription job: {e}\n{error_details}")
        transcription_requests_total.labels(
            status="error",
            model_size=model_size.value,
            format="unknown",
        ).inc()
        raise HTTPException(status_code=500, detail=f"Failed to process upload: {str(e)}")


@router.post("/url", response_model=TranscribeResponse)
async def transcribe_url(
    request: TranscribeURLRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Transcribe audio from a URL.

    The audio will be downloaded and processed asynchronously.
    """
    # SSRF protection: reject internal/private URLs
    if _is_internal_url(request.url):
        raise HTTPException(
            status_code=400,
            detail="URLs pointing to internal or private networks are not allowed",
        )

    job_id = str(uuid.uuid4())

    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
            max_redirects=5,
            follow_redirects=True,
        ) as client:
            response = await client.get(request.url)
            response.raise_for_status()

            content_length_header = response.headers.get("content-length")
            if content_length_header:
                try:
                    if int(content_length_header) > settings.max_file_size_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB"
                        )
                except ValueError:
                    pass

            content = response.content
            content_type = response.headers.get("content-type", "audio/mpeg")

        # Determine format
        if content_type in ALLOWED_FORMATS:
            audio_format = ALLOWED_FORMATS[content_type]
        else:
            url_path = urlparse(str(request.url)).path
            ext = os.path.splitext(url_path)[1].lower().lstrip(".")
            if ext in ALLOWED_FORMATS.values():
                audio_format = ext
            else:
                raise HTTPException(status_code=400, detail="Unsupported audio format")

        file_size = len(content)
        if file_size > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB"
            )

        storage = get_storage()
        object_name = f"uploads/{job_id}/audio.{audio_format}"
        storage.upload_bytes(content, object_name, content_type=content_type)

        key_hash = get_api_key_hash(api_key)
        job = create_job(object_name, audio_format, file_size, request.options, key_hash)

        try:
            submit_transcription_task(job, request.options)
        except Exception as celery_exc:
            delete_job(str(job.id))
            logger.error(f"Failed to submit task to Celery (Redis unavailable?): {celery_exc}")
            raise HTTPException(
                status_code=503,
                detail="Task queue is unavailable. Please try again later.",
            )

        logger.info(f"Created URL transcription job", extra={"job_id": str(job.id)})

        return TranscribeResponse(
            job_id=str(job.id),
            status=JobStatus.QUEUED,
            created_at=job.created_at,
        )

    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download URL: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create URL transcription job: {e}")
        raise HTTPException(status_code=500, detail="Failed to process URL")


@router.post("/batch", response_model=BatchJobResponse)
async def transcribe_batch(
    request: BatchTranscribeRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Submit multiple URLs for batch transcription.

    All files will be processed with the same options.
    """
    batch_id = str(uuid.uuid4())
    jobs = []
    failed_urls = []

    for url in request.urls:
        try:
            url_request = TranscribeURLRequest(url=url, options=request.options)
            job_response = await transcribe_url(url_request, api_key)
            jobs.append(job_response)
        except HTTPException as e:
            logger.error(f"Failed to queue URL in batch: {url}, error: {e.detail}")
            failed_urls.append(BatchJobFailure(url=url, error=str(e.detail)))
        except Exception as e:
            logger.error(f"Failed to queue URL in batch: {url}, error: {e}")
            failed_urls.append(BatchJobFailure(url=url, error=str(e)))

    return BatchJobResponse(
        batch_id=batch_id,
        jobs=jobs,
        total_jobs=len(jobs),
        failed_urls=failed_urls,
    )
