"""
WebSocket endpoint for real-time transcription progress streaming.

Usage:
    ws://api-host/ws/jobs/{job_id}

The client connects and receives JSON progress events as the worker
processes the transcription job.  The connection closes automatically
when the job reaches a terminal state (completed / failed / cancelled).

Event format:
    {
        "job_id": "uuid",
        "status": "processing",
        "progress": 60,
        "current_step": "transcribing",
        "error_message": null
    }

Implementation:
    - Worker publishes events to Redis pub/sub channel  job:{job_id}:progress
    - WebSocket handler subscribes and forwards events to the client
    - Fallback: if Redis pub/sub is unavailable, polls the DB every 2 seconds
"""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.websockets import WebSocketState

from common.config import settings
from common.database import db_session, TranscriptionJob, JobStatus
from common.logging_config import get_logger

logger = get_logger("api.routes.ws")

router = APIRouter(tags=["WebSocket"])

# Terminal states — connection closes after receiving one of these
TERMINAL_STATUSES = {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}

# How long to wait between DB-poll attempts when Redis pub/sub is unavailable
DB_POLL_INTERVAL = 2.0  # seconds

# Maximum time to keep a WebSocket connection open (prevents zombie connections)
MAX_CONNECTION_SECONDS = 3600  # 1 hour


async def _send_safe(ws: WebSocket, data: dict) -> bool:
    """Send JSON message to client; return False on disconnect."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)
            return True
    except Exception:
        pass
    return False


async def _stream_via_pubsub(ws: WebSocket, job_id: str) -> None:
    """Stream progress events via Redis pub/sub."""
    import redis.asyncio as aioredis

    channel = f"job:{job_id}:progress"
    r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
    pubsub = r.pubsub()

    try:
        await pubsub.subscribe(channel)
        logger.info(f"WebSocket subscribed to Redis channel: {channel}")

        deadline = asyncio.get_event_loop().time() + MAX_CONNECTION_SECONDS

        while asyncio.get_event_loop().time() < deadline:
            message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)

            if message and message.get("type") == "message":
                try:
                    data = json.loads(message["data"])
                except (ValueError, TypeError):
                    continue

                ok = await _send_safe(ws, data)
                if not ok:
                    break

                if data.get("status") in TERMINAL_STATUSES:
                    logger.info(f"Job {job_id} reached terminal state via pub/sub")
                    break

    except asyncio.TimeoutError:
        pass  # normal: no message within timeout, loop again
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await r.aclose()


async def _stream_via_polling(ws: WebSocket, job_id: str) -> None:
    """Fallback: stream progress events by polling the database."""
    logger.info(f"WebSocket fallback: polling DB for job {job_id}")
    deadline = asyncio.get_event_loop().time() + MAX_CONNECTION_SECONDS

    while asyncio.get_event_loop().time() < deadline:
        with db_session() as db:
            job: Optional[TranscriptionJob] = db.query(TranscriptionJob).filter(
                TranscriptionJob.id == job_id
            ).first()

        if job is None:
            await _send_safe(ws, {"error": "job not found", "job_id": job_id})
            break

        data = {
            "job_id": job_id,
            "status": job.status.value,
            "progress": job.progress,
            "current_step": job.current_step,
            "error_message": job.error_message,
        }

        ok = await _send_safe(ws, data)
        if not ok:
            break

        if job.status.value in TERMINAL_STATUSES:
            logger.info(f"Job {job_id} reached terminal state via polling")
            break

        await asyncio.sleep(DB_POLL_INTERVAL)


@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_progress(
    websocket: WebSocket,
    job_id: str,
) -> None:
    """
    Stream real-time transcription progress for a job.

    Connect to receive JSON progress events until the job completes.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection opened for job {job_id}")

    # Quick sanity check: does the job exist?
    with db_session() as db:
        job = db.query(TranscriptionJob).filter(TranscriptionJob.id == job_id).first()

    if job is None:
        await websocket.send_json({"error": "job not found", "job_id": job_id})
        await websocket.close(code=4004)
        return

    # If job is already in terminal state, send final event and close
    if job.status.value in TERMINAL_STATUSES:
        await websocket.send_json({
            "job_id": job_id,
            "status": job.status.value,
            "progress": job.progress,
            "current_step": job.current_step,
            "error_message": job.error_message,
        })
        await websocket.close()
        return

    try:
        # Try Redis pub/sub first; fall back to polling if unavailable
        try:
            import redis.asyncio  # noqa: F401 — check availability
            await _stream_via_pubsub(websocket, job_id)
        except (ImportError, Exception) as exc:
            logger.warning(f"Redis pub/sub unavailable ({exc}), falling back to polling")
            await _stream_via_polling(websocket, job_id)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for job {job_id}")
    except Exception as exc:
        logger.error(f"WebSocket error for job {job_id}: {exc}")
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info(f"WebSocket connection closed for job {job_id}")
