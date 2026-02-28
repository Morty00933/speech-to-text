"""
Integration tests for transcription endpoints.
"""
import io
import pytest
from fastapi.testclient import TestClient


class TestTranscribeFile:
    """Tests for POST /transcribe/file."""

    def test_upload_valid_wav_returns_job_id(
        self, client: TestClient, valid_headers: dict, valid_audio_bytes: bytes
    ):
        """Uploading a valid WAV file must create a job and return job_id."""
        response = client.post(
            "/transcribe/file",
            headers=valid_headers,
            files={"file": ("test.wav", io.BytesIO(valid_audio_bytes), "audio/wav")},
            data={"model_size": "tiny"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    def test_upload_requires_auth(self, client: TestClient, valid_audio_bytes: bytes):
        """Upload without credentials must be rejected."""
        response = client.post(
            "/transcribe/file",
            files={"file": ("test.wav", io.BytesIO(valid_audio_bytes), "audio/wav")},
        )
        assert response.status_code == 401

    def test_upload_unsupported_format_returns_400(
        self, client: TestClient, valid_headers: dict
    ):
        """Uploading a non-audio file must return 400."""
        response = client.post(
            "/transcribe/file",
            headers=valid_headers,
            files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 400
        assert "format" in response.json()["detail"].lower()

    def test_upload_mp3_content_type_accepted(
        self, client: TestClient, valid_headers: dict
    ):
        """audio/mpeg content-type must be accepted."""
        response = client.post(
            "/transcribe/file",
            headers=valid_headers,
            files={"file": ("audio.mp3", io.BytesIO(b"\xFF\xFB" + b"\x00" * 100), "audio/mpeg")},
            data={"model_size": "tiny"},
        )
        # Should be 200 (queued) not 400 (format rejection)
        assert response.status_code == 200

    def test_upload_opus_content_type_accepted(
        self, client: TestClient, valid_headers: dict
    ):
        """audio/opus content-type must now be accepted (new feature)."""
        response = client.post(
            "/transcribe/file",
            headers=valid_headers,
            files={"file": ("voice.opus", io.BytesIO(b"OggS" + b"\x00" * 50), "audio/opus")},
            data={"model_size": "tiny"},
        )
        assert response.status_code == 200


class TestTranscribeURL:
    """Tests for POST /transcribe/url."""

    def test_internal_url_blocked(self, client: TestClient, valid_headers: dict):
        """URLs pointing to internal/private networks must be rejected (SSRF)."""
        internal_urls = [
            "http://localhost/audio.mp3",
            "http://127.0.0.1/audio.mp3",
            "http://192.168.1.1/audio.mp3",
            "http://10.0.0.1/audio.mp3",
        ]
        for url in internal_urls:
            response = client.post(
                "/transcribe/url",
                headers=valid_headers,
                json={"url": url, "options": {}},
            )
            assert response.status_code in (400, 422), (
                f"Expected 400/422 for internal URL {url}, got {response.status_code}"
            )

    def test_url_without_auth_rejected(self, client: TestClient):
        """URL transcription without credentials must fail."""
        response = client.post(
            "/transcribe/url",
            json={"url": "http://example.com/audio.mp3", "options": {}},
        )
        assert response.status_code == 401


class TestTranscribeBatch:
    """Tests for POST /transcribe/batch."""

    def test_batch_without_auth_rejected(self, client: TestClient):
        """Batch endpoint without credentials must return 401."""
        response = client.post(
            "/transcribe/batch",
            json={"urls": ["http://example.com/a.mp3"], "options": {}},
        )
        assert response.status_code == 401

    def test_batch_empty_urls_returns_422(self, client: TestClient, valid_headers: dict):
        """Empty URLs list must fail Pydantic validation."""
        response = client.post(
            "/transcribe/batch",
            headers=valid_headers,
            json={"urls": [], "options": {}},
        )
        assert response.status_code == 422

    def test_batch_invalid_options_rejected(self, client: TestClient, valid_headers: dict):
        """Invalid model_size must return 422."""
        response = client.post(
            "/transcribe/batch",
            headers=valid_headers,
            json={
                "urls": ["http://example.com/a.mp3"],
                "options": {"model_size": "nonexistent-model"},
            },
        )
        assert response.status_code == 422
