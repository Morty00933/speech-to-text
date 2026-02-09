"""
Job management endpoints.
"""
import json
import os
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc

from common.config import settings
from common.logging_config import get_logger
from common.storage import get_storage
from common.database import db_session, TranscriptionJob, JobStatus as DBJobStatus
from common.celery_client import celery_app
from common.models_registry import WHISPER_MODELS
from auth import verify_api_key, get_api_key_hash

from schemas import (
    JobStatus,
    JobStatusResponse,
    TranscriptionResult,
    Segment,
    Speaker,
    TranscriptionMetadata,
    ModelsResponse,
    ModelInfo,
)

logger = get_logger("jobs")
router = APIRouter(prefix="/jobs", tags=["Jobs"])


MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR", "/models")


def _is_downloaded(model_name: str) -> bool:
    """Check if a faster-whisper model is present in the local cache.

    Supports two storage layouts:
    1. HuggingFace Hub cache  — ``models--Systran--faster-whisper-{name}/snapshots/``
       (created by ``hf_hub_download`` / ``huggingface_hub`` default cache)
    2. Flat snapshot layout   — ``faster-whisper-{name}/model.bin``
       (created by ``snapshot_download(..., local_dir=...)`` used in ``make download-model-*``)
    """
    # Layout 1: HuggingFace Hub cache
    hf_dir = os.path.join(
        MODEL_CACHE_DIR,
        f"models--Systran--faster-whisper-{model_name}",
        "snapshots",
    )
    if os.path.isdir(hf_dir):
        try:
            return any(True for _ in os.scandir(hf_dir))
        except OSError:
            pass

    # Layout 2: Flat snapshot_download layout (make download-model-*)
    flat_dir = os.path.join(MODEL_CACHE_DIR, f"faster-whisper-{model_name}")
    if os.path.isdir(flat_dir):
        return os.path.isfile(os.path.join(flat_dir, "model.bin"))

    return False


def _get_job(db, job_id: str, api_key_hash: str) -> TranscriptionJob:
    """Get job by ID with API key verification.

    Must be called inside a ``db_session()`` context manager — the returned
    object stays attached to *db* so all attributes remain accessible.
    """
    job = db.query(TranscriptionJob).filter(
        TranscriptionJob.id == job_id,
        TranscriptionJob.api_key_hash == api_key_hash,
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/models", response_model=ModelsResponse)
async def list_models():
    """List available transcription models."""
    models_with_status = [
        ModelInfo(
            name=m.name,
            size=m.parameters,
            vram_required_gb=m.vram_required_gb,
            languages=m.languages,
            description=m.description,
            recommended_for=m.recommended_for,
            downloaded=_is_downloaded(m.name),
        )
        for m in WHISPER_MODELS
    ]
    return ModelsResponse(
        models=models_with_status,
        default_model=settings.default_model_size,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get the status of a transcription job."""
    key_hash = get_api_key_hash(api_key)

    with db_session() as db:
        job = _get_job(db, job_id, key_hash)

        # Calculate estimated time remaining
        estimated_remaining = None
        if job.status == DBJobStatus.PROCESSING and job.progress and job.progress > 0:
            if job.started_at:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                started = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
                elapsed = (now - started).total_seconds()
                estimated_total = elapsed / (job.progress / 100)
                estimated_remaining = max(0, int(estimated_total - elapsed))

        return JobStatusResponse(
            job_id=str(job.id),
            status=JobStatus(job.status.value),
            progress=job.progress or 0,
            current_step=job.current_step,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            estimated_time_remaining=estimated_remaining,
            error=job.error_message,
        )


@router.get("/{job_id}/result", response_model=TranscriptionResult)
async def get_job_result(
    job_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get the result of a completed transcription job."""
    key_hash = get_api_key_hash(api_key)

    with db_session() as db:
        job = _get_job(db, job_id, key_hash)

        if job.status == DBJobStatus.QUEUED:
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": str(job.id),
                    "status": "queued",
                    "message": "Job is still queued",
                    "retry_after": 30,
                },
                headers={"Retry-After": "30"},
            )

        if job.status == DBJobStatus.PROCESSING:
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": str(job.id),
                    "status": "processing",
                    "progress": job.progress or 0,
                    "message": f"Job is processing ({job.progress or 0}%)",
                    "retry_after": 10,
                },
                headers={"Retry-After": "10"},
            )

        if job.status == DBJobStatus.FAILED:
            return TranscriptionResult(
                job_id=str(job.id),
                status=JobStatus.FAILED,
                error=job.error_message,
            )

        if job.status == DBJobStatus.CANCELLED:
            return TranscriptionResult(
                job_id=str(job.id),
                status=JobStatus.CANCELLED,
            )

        # Get result from storage
        try:
            if job.result_path:
                storage = get_storage()
                result_data = storage.get_file_bytes(job.result_path)
                result = json.loads(result_data.decode())
            else:
                result = {"text": job.result_text, "segments": []}
        except Exception as e:
            logger.error(f"Failed to retrieve result for job {job_id}: {e}")
            result = {"text": job.result_text, "segments": []}

        # Build response
        segments = [
            Segment(
                start=s.get("start", 0),
                end=s.get("end", 0),
                text=s.get("text", ""),
                speaker=s.get("speaker"),
                confidence=s.get("confidence"),
            )
            for s in result.get("segments", [])
        ]

        speakers = None
        if result.get("speakers"):
            speakers = [
                Speaker(
                    id=s.get("id", ""),
                    segments_count=s.get("segments_count", 0),
                    total_duration=s.get("total_duration", 0),
                )
                for s in result.get("speakers", [])
            ]

        metadata = TranscriptionMetadata(
            language=job.detected_language or result.get("language", "unknown"),
            duration=job.audio_duration or result.get("duration", 0),
            processing_time=job.processing_time or 0,
            model_used=job.model_size,
            audio_format=job.audio_format,
        )

        return TranscriptionResult(
            job_id=str(job.id),
            status=JobStatus.COMPLETED,
            text=result.get("text", job.result_text),
            segments=segments,
            speakers=speakers,
            metadata=metadata,
        )


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Cancel a pending or processing job."""
    key_hash = get_api_key_hash(api_key)

    with db_session() as db:
        job = _get_job(db, job_id, key_hash)

        if job.status not in [DBJobStatus.QUEUED, DBJobStatus.PROCESSING]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status: {job.status.value}",
            )

        job.status = DBJobStatus.CANCELLED
        db.commit()

        # Revoke the Celery task (best-effort)
        try:
            celery_app.control.revoke(job_id, terminate=True, signal="SIGTERM")
        except Exception as e:
            logger.warning(f"Could not revoke Celery task {job_id}: {e}")

        logger.info(f"Cancelled job", extra={"job_id": job_id})

        return {"message": "Job cancelled", "job_id": job_id}


@router.get("/", response_model=List[JobStatusResponse])
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    api_key: str = Depends(verify_api_key),
):
    """List all transcription jobs (paginated)."""
    key_hash = get_api_key_hash(api_key)

    with db_session() as db:
        query = db.query(TranscriptionJob).filter(
            TranscriptionJob.api_key_hash == key_hash
        )

        if status:
            query = query.filter(TranscriptionJob.status == DBJobStatus(status.value))

        jobs = query.order_by(desc(TranscriptionJob.created_at)).offset(offset).limit(limit).all()

        return [
            JobStatusResponse(
                job_id=str(job.id),
                status=JobStatus(job.status.value),
                progress=job.progress or 0,
                current_step=job.current_step,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error=job.error_message,
            )
            for job in jobs
        ]
