"""
Celery tasks for speech-to-text processing.
"""
import os
import json
import time
import tempfile
from typing import Dict, Any, Optional

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from celery_app import app

from common.config import settings
from common.logging_config import setup_logging, get_logger
from common.storage import get_storage
from common.database import db_session, TranscriptionJob, JobStatus
from common.metrics import (
    transcription_requests_total,
    transcription_errors_total,
    jobs_completed_total,
    active_jobs,
    audio_duration_seconds,
)

# Setup logging
setup_logging(settings.log_level, settings.log_format, "stt.worker")
logger = get_logger("worker.tasks")


def _publish_progress(job_id: str, data: dict) -> None:
    """Publish job progress event to Redis pub/sub channel.

    Used by WebSocket clients to receive real-time updates.
    Silently ignores failures so the main transcription flow is unaffected.
    """
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=1)
        channel = f"job:{job_id}:progress"
        r.publish(channel, json.dumps(data))
    except Exception as exc:
        logger.debug(f"pub/sub publish failed (non-fatal): {exc}")


class TranscriptionTask(Task):
    """Base task with model management."""

    _engine = None
    _preprocessor = None
    _diarizer = None
    _postprocessor = None

    # Graceful degradation: tracks whether the model failed to load so that
    # subsequent tasks fail fast with a clear message instead of re-attempting
    # an expensive (and doomed) model download on every call.
    _model_unavailable: bool = False
    _model_unavailable_reason: str = ""

    @property
    def engine(self):
        """Lazy load transcription engine with graceful degradation."""
        if self._model_unavailable:
            raise RuntimeError(
                f"Transcription model is unavailable: {self._model_unavailable_reason}. "
                f"Run: make download-model-{settings.default_model_size}"
            )

        if self._engine is None:
            from transcriber.engine import TranscriptionEngine
            engine = TranscriptionEngine(model_size=settings.default_model_size)
            try:
                engine.load_model()
                self._engine = engine
            except Exception as exc:
                # Mark as unavailable so future tasks fail immediately
                self.__class__._model_unavailable = True
                self.__class__._model_unavailable_reason = str(exc)
                logger.error(
                    f"Failed to load transcription model — marking worker as degraded",
                    extra={"error": str(exc)},
                )
                raise RuntimeError(
                    f"Failed to load model '{settings.default_model_size}': {exc}. "
                    f"Run: make download-model-{settings.default_model_size}"
                ) from exc
        return self._engine

    @property
    def preprocessor(self):
        """Lazy load audio preprocessor."""
        if self._preprocessor is None:
            from transcriber.preprocessor import AudioPreprocessor
            self._preprocessor = AudioPreprocessor()
        return self._preprocessor

    @property
    def diarizer(self):
        """Lazy load speaker diarizer."""
        if self._diarizer is None:
            from transcriber.diarizer import get_diarizer
            self._diarizer = get_diarizer()
        return self._diarizer

    @property
    def postprocessor(self):
        """Lazy load postprocessor.

        ML punctuation model (deepmultilingualpunctuation) is disabled:
        - It downloads ~1.6 GB on first use, causing 85%+ hang
        - Whisper already produces punctuation for most languages
        - Rule-based fallback in Postprocessor is fast and sufficient
        """
        if self._postprocessor is None:
            from transcriber.postprocessor import Postprocessor
            self._postprocessor = Postprocessor(use_punctuation_model=False)
        return self._postprocessor


def update_job_status(
    job_id: str,
    status: JobStatus,
    progress: int = None,
    current_step: str = None,
    error_message: str = None,
    **kwargs
):
    """Update job status in database and publish progress event to Redis pub/sub."""
    with db_session() as db:
        job = db.query(TranscriptionJob).filter(
            TranscriptionJob.id == job_id
        ).first()

        if job:
            job.status = status
            if progress is not None:
                job.progress = progress
            if current_step:
                job.current_step = current_step
            if error_message:
                job.error_message = error_message

            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)

            db.commit()
            logger.info(
                f"Updated job status",
                extra={"job_id": job_id, "status": status.value, "progress": progress}
            )

    # Publish to WebSocket subscribers (best-effort, non-blocking)
    _publish_progress(job_id, {
        "job_id": job_id,
        "status": status.value,
        "progress": progress,
        "current_step": current_step,
        "error_message": error_message,
    })


def save_result(job_id: str, result: Dict[str, Any]) -> str:
    """Save transcription result to storage."""
    storage = get_storage()
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    object_name = f"results/{job_id}/transcription.json"
    storage.upload_bytes(
        result_json.encode("utf-8"),
        object_name,
        content_type="application/json"
    )
    return object_name


def _transcribe_chunked(
    task: "TranscriptionTask",
    audio_path: str,
    options: Dict[str, Any],
    job_id: str,
) -> Any:
    """
    Transcribe a long audio file by splitting it into overlapping 30-minute chunks.

    Progress is reported linearly from 20% to 60% as chunks are processed.
    Segment timestamps are adjusted to reflect the position in the original audio.

    Returns a TranscriptionResult-compatible object with merged segments.
    """
    from transcriber.engine import TranscriptionResult, TranscriptionSegment

    chunks = task.preprocessor.split_audio_chunks(
        audio_path,
        chunk_duration=1800.0,  # 30 min
        overlap=30.0,           # 30 s overlap to avoid cutting words
    )

    all_segments = []
    detected_language = None
    language_probability = 0.0
    total_processing_time = 0.0
    total_duration = 0.0
    seen_end_times: set = set()

    for i, (chunk_path, start_offset) in enumerate(chunks):
        try:
            progress = 20 + int((i / len(chunks)) * 40)
            update_job_status(
                job_id, JobStatus.PROCESSING,
                progress=progress,
                current_step=f"transcribing chunk {i + 1}/{len(chunks)}",
            )

            result = task.engine.transcribe(
                chunk_path,
                language=options.get("language"),
                word_timestamps=options.get("enable_timestamps", True),
            )

            # Detect language from first chunk
            if detected_language is None:
                detected_language = result.language
                language_probability = result.language_probability

            total_processing_time += result.processing_time
            if i == len(chunks) - 1:
                total_duration = start_offset + result.duration

            # Adjust segment timestamps relative to original audio
            # Skip segments whose end time overlaps with previously processed region
            # (deduplication for the overlapping region)
            for seg in result.segments:
                abs_start = seg.start + start_offset
                abs_end = seg.end + start_offset

                # Round to 2 decimals for overlap dedup
                rounded_end = round(abs_end, 2)
                if rounded_end in seen_end_times:
                    continue  # duplicate from overlap region

                seen_end_times.add(rounded_end)

                adjusted_seg = TranscriptionSegment(
                    start=abs_start,
                    end=abs_end,
                    text=seg.text,
                    words=[
                        {**w, "start": w["start"] + start_offset, "end": w["end"] + start_offset}
                        for w in (seg.words or [])
                    ],
                    confidence=seg.confidence,
                )
                all_segments.append(adjusted_seg)

        finally:
            # Always clean up temp chunk files
            try:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
            except OSError:
                pass

    full_text = " ".join(s.text for s in all_segments)

    return TranscriptionResult(
        text=full_text,
        segments=all_segments,
        language=detected_language or "unknown",
        language_probability=language_probability,
        duration=total_duration,
        processing_time=total_processing_time,
    )


@app.task(
    bind=True,
    base=TranscriptionTask,
    max_retries=3,
    name="tasks.transcribe_audio",
    soft_time_limit=600,
    time_limit=660,
)
def transcribe_audio(
    self,
    job_id: str,
    audio_path: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Main transcription task.

    Args:
        job_id: Unique job identifier
        audio_path: Path to audio file in storage
        options: Transcription options

    Returns:
        Result dictionary with job_id and status
    """
    start_time = time.time()
    temp_files = []
    active_jobs.inc()

    try:
        logger.info(f"Starting transcription job", extra={"job_id": job_id})

        # Guard: if job was cancelled before the worker picked it up, stop immediately
        with db_session() as db:
            job_check = db.query(TranscriptionJob).filter(
                TranscriptionJob.id == job_id
            ).first()
            if job_check and job_check.status == JobStatus.CANCELLED:
                logger.info(f"Job was cancelled before processing started, skipping", extra={"job_id": job_id})
                return {"job_id": job_id, "status": "cancelled"}

        def _check_cancelled() -> bool:
            """Return True if the job was cancelled in the DB mid-flight."""
            try:
                with db_session() as _db:
                    _j = _db.query(TranscriptionJob).filter(
                        TranscriptionJob.id == job_id
                    ).first()
                    return _j is not None and _j.status == JobStatus.CANCELLED
            except Exception:
                return False

        # Update status to processing
        update_job_status(job_id, JobStatus.PROCESSING, progress=0, current_step="downloading")

        # Download audio from storage
        storage = get_storage()
        fd, local_audio_path = tempfile.mkstemp(suffix=".audio")
        os.close(fd)
        temp_files.append(local_audio_path)

        storage.download_file(audio_path, local_audio_path)

        # Get audio info
        audio_info = self.preprocessor.get_audio_info(local_audio_path)
        audio_duration = audio_info.get("duration", 0)

        audio_duration_seconds.labels(
            format=audio_info.get("format", "unknown")
        ).observe(audio_duration)

        update_job_status(
            job_id, JobStatus.PROCESSING,
            progress=10,
            current_step="preprocessing",
            audio_duration=audio_duration,
            audio_format=audio_info.get("format"),
        )

        # Preprocess audio
        preprocessed_path = self.preprocessor.preprocess(
            local_audio_path,
            remove_silence=False,
            normalize=True,
        )
        if preprocessed_path != local_audio_path:
            temp_files.append(preprocessed_path)

        update_job_status(job_id, JobStatus.PROCESSING, progress=20, current_step="transcribing")

        # Mid-flight cancellation check — before the expensive transcription call
        if _check_cancelled():
            logger.info(f"Job cancelled before transcription, stopping", extra={"job_id": job_id})
            return {"job_id": job_id, "status": "cancelled"}

        # Transcribe
        model_size = options.get("model_size", settings.default_model_size)

        # Load or reload model with the requested size.
        # The ``engine`` property always uses ``settings.default_model_size``, so
        # we manage the engine directly here to respect the per-job model_size.
        from transcriber.engine import TranscriptionEngine
        if self._engine is None:
            logger.info(f"Loading engine with model: {model_size}", extra={"job_id": job_id})
            self._engine = TranscriptionEngine(model_size=model_size)
            self._engine.load_model()
        elif model_size != self._engine.model_size:
            logger.info(
                f"Model size changed from {self._engine.model_size} to {model_size}, reloading",
                extra={"job_id": job_id}
            )
            self._engine.unload_model()
            self._engine = None
            self._engine = TranscriptionEngine(model_size=model_size)
            self._engine.load_model()

        # Long audio (>30 min) → chunked transcription with overlap
        CHUNK_THRESHOLD_SECONDS = 1800.0  # 30 minutes
        if audio_duration > CHUNK_THRESHOLD_SECONDS:
            logger.info(
                f"Audio is {audio_duration:.0f}s (>{CHUNK_THRESHOLD_SECONDS:.0f}s), "
                f"using chunked transcription",
                extra={"job_id": job_id}
            )
            transcription = _transcribe_chunked(
                self, preprocessed_path, options, job_id
            )
        else:
            transcription = self.engine.transcribe(
                preprocessed_path,
                language=options.get("language"),
                word_timestamps=options.get("enable_timestamps", True),
            )

        update_job_status(job_id, JobStatus.PROCESSING, progress=60, current_step="postprocessing")

        # Convert segments to dict format
        segments = [
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": seg.words,
                "confidence": seg.confidence,
            }
            for seg in transcription.segments
        ]

        # Speaker diarization (if enabled)
        speakers_info = None
        diarization_mode = None
        if options.get("enable_diarization", False):
            update_job_status(job_id, JobStatus.PROCESSING, progress=70, current_step="diarizing")

            from transcriber.diarizer import SimpleDiarizer
            diarization_mode = "simple" if isinstance(self.diarizer, SimpleDiarizer) else "full"

            try:
                diar_segments = self.diarizer.diarize(
                    local_audio_path,
                    min_speakers=options.get("min_speakers", 1),
                    max_speakers=options.get("max_speakers"),
                )

                segments = self.diarizer.align_with_transcription(segments, diar_segments)

                speakers_info = [
                    {"id": s.id, "segments_count": s.segments_count, "total_duration": s.total_duration}
                    for s in self.diarizer.get_speaker_info(diar_segments)
                ]
            except Exception as e:
                logger.warning(f"Diarization failed, continuing without: {e}")

        update_job_status(job_id, JobStatus.PROCESSING, progress=85, current_step="formatting")

        # Post-processing
        if options.get("enable_punctuation", True):
            processed_segments = self.postprocessor.process_segments(
                segments,
                restore_punctuation=True,
            )
            segments = [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "speaker": s.speaker,
                    "confidence": s.confidence,
                }
                for s in processed_segments
            ]

        # Build result
        full_text = " ".join(s["text"] for s in segments)
        result = {
            "text": full_text,
            "segments": segments,
            "language": transcription.language,
            "language_probability": transcription.language_probability,
            "duration": audio_duration,
            "processing_time": time.time() - start_time,
            "model_used": model_size,
        }

        if speakers_info:
            result["speakers"] = speakers_info

        if diarization_mode:
            result["diarization_mode"] = diarization_mode

        # Format output if needed (reuse the existing postprocessor instance)
        output_format = options.get("output_format", "json")
        if output_format != "json":
            from transcriber.postprocessor import ProcessedSegment
            processed = [
                ProcessedSegment(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    speaker=s.get("speaker"),
                    confidence=s.get("confidence"),
                )
                for s in segments
            ]
            result["formatted_output"] = self.postprocessor.format_output(
                processed,
                format=output_format,
                include_speakers=options.get("enable_diarization", False),
            )

        update_job_status(job_id, JobStatus.PROCESSING, progress=95, current_step="saving")

        # Save result
        result_path = save_result(job_id, result)

        # Update job as completed
        processing_time = time.time() - start_time
        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            current_step="completed",
            result_path=result_path,
            result_text=full_text[:10000],
            detected_language=transcription.language,
            speakers_count=len(speakers_info) if speakers_info else None,
            processing_time=processing_time,
        )

        # Update metrics
        jobs_completed_total.labels(status="success").inc()
        transcription_requests_total.labels(
            status="completed",
            model_size=model_size,
            format=output_format,
        ).inc()

        logger.info(
            f"Transcription completed",
            extra={
                "job_id": job_id,
                "processing_time": processing_time,
                "audio_duration": audio_duration,
            }
        )

        return {"job_id": job_id, "status": "completed"}

    except SoftTimeLimitExceeded:
        logger.error(f"Task timeout", extra={"job_id": job_id})
        update_job_status(job_id, JobStatus.FAILED, error_message="Task timeout")
        jobs_completed_total.labels(status="failed").inc()
        transcription_errors_total.labels(error_type="timeout", model_size=options.get("model_size", "unknown")).inc()
        raise

    except Exception as e:
        logger.error(f"Transcription failed: {e}", extra={"job_id": job_id}, exc_info=True)

        # Only update to FAILED if the job wasn't cancelled while we were processing
        with db_session() as db:
            job_now = db.query(TranscriptionJob).filter(
                TranscriptionJob.id == job_id
            ).first()
            if job_now and job_now.status == JobStatus.CANCELLED:
                logger.info(f"Job was cancelled during processing, not marking as FAILED", extra={"job_id": job_id})
                jobs_completed_total.labels(status="cancelled").inc()
                return {"job_id": job_id, "status": "cancelled"}

        update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        jobs_completed_total.labels(status="failed").inc()
        transcription_errors_total.labels(
            error_type=type(e).__name__,
            model_size=options.get("model_size", "unknown")
        ).inc()

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    finally:
        active_jobs.dec()
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.debug(f"Removed temp file: {temp_file}")
            except OSError as cleanup_err:
                logger.warning(
                    f"Failed to remove temp file {temp_file}: {cleanup_err}",
                    extra={"job_id": job_id}
                )
