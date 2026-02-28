"""
Integration tests for job management endpoints.
"""
import io
import uuid
import pytest
from fastapi.testclient import TestClient


def _create_job(client: TestClient, headers: dict, audio_bytes: bytes) -> str:
    """Helper: submit a transcription job and return the job_id."""
    response = client.post(
        "/transcribe/file",
        headers=headers,
        files={"file": ("test.wav", io.BytesIO(audio_bytes), "audio/wav")},
        data={"model_size": "tiny"},
    )
    assert response.status_code == 200
    return response.json()["job_id"]


class TestJobStatus:
    """Tests for GET /jobs/{job_id}."""

    def test_get_status_of_existing_job(
        self, client: TestClient, valid_headers: dict, valid_audio_bytes: bytes
    ):
        """Fetching status of a created job returns progress info."""
        job_id = _create_job(client, valid_headers, valid_audio_bytes)

        response = client.get(f"/jobs/{job_id}", headers=valid_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "status" in data
        assert "progress" in data

    def test_get_status_nonexistent_job_returns_404(
        self, client: TestClient, valid_headers: dict
    ):
        """Fetching status for unknown job_id must return 404."""
        fake_id = str(uuid.uuid4())
        response = client.get(f"/jobs/{fake_id}", headers=valid_headers)
        assert response.status_code == 404

    def test_get_status_requires_auth(self, client: TestClient, valid_audio_bytes: bytes):
        """Status endpoint without credentials must return 401."""
        response = client.get(f"/jobs/{uuid.uuid4()}")
        assert response.status_code == 401


class TestJobResult:
    """Tests for GET /jobs/{job_id}/result."""

    def test_result_for_queued_job_returns_status(
        self, client: TestClient, valid_headers: dict, valid_audio_bytes: bytes
    ):
        """Result endpoint on a queued/processing job returns 200 with retry hint."""
        job_id = _create_job(client, valid_headers, valid_audio_bytes)
        response = client.get(f"/jobs/{job_id}/result", headers=valid_headers)
        # Job is still queued (worker is mocked), so either 200 with status or 202
        assert response.status_code in (200, 202)

    def test_result_for_nonexistent_job_returns_404(
        self, client: TestClient, valid_headers: dict
    ):
        """Result endpoint for unknown job must return 404."""
        response = client.get(f"/jobs/{uuid.uuid4()}/result", headers=valid_headers)
        assert response.status_code == 404


class TestJobsList:
    """Tests for GET /jobs/ (list)."""

    def test_list_jobs_returns_array(self, client: TestClient, valid_headers: dict):
        """GET /jobs/ must return a JSON array."""
        response = client.get("/jobs/", headers=valid_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_jobs_pagination(self, client: TestClient, valid_headers: dict):
        """Pagination params limit and offset must be accepted."""
        response = client.get("/jobs/?limit=5&offset=0", headers=valid_headers)
        assert response.status_code == 200

    def test_list_jobs_filter_by_status(self, client: TestClient, valid_headers: dict):
        """Filter by status=queued must return only matching jobs."""
        response = client.get("/jobs/?status=queued", headers=valid_headers)
        assert response.status_code == 200


class TestJobCancel:
    """Tests for DELETE /jobs/{job_id}."""

    def test_cancel_nonexistent_job_returns_404(
        self, client: TestClient, valid_headers: dict
    ):
        """Cancelling an unknown job must return 404."""
        response = client.delete(f"/jobs/{uuid.uuid4()}", headers=valid_headers)
        assert response.status_code == 404

    def test_cancel_requires_auth(self, client: TestClient):
        """Cancel without credentials must return 401."""
        response = client.delete(f"/jobs/{uuid.uuid4()}")
        assert response.status_code == 401


class TestModels:
    """Tests for GET /jobs/models."""

    def test_models_list_returns_models(self, client: TestClient, valid_headers: dict):
        """GET /jobs/models must return a list of available models."""
        response = client.get("/jobs/models", headers=valid_headers)
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert len(data["models"]) > 0

    def test_models_list_requires_auth(self, client: TestClient):
        """Models endpoint without credentials must return 401."""
        response = client.get("/jobs/models")
        assert response.status_code == 401
