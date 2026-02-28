"""
Integration tests for authentication (API key + JWT).
"""
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_API_KEY


class TestApiKeyAuth:
    """Tests for X-API-Key authentication."""

    def test_missing_api_key_returns_401(self, client: TestClient):
        """Requests without any credentials must be rejected."""
        response = client.get("/jobs/")
        assert response.status_code == 401

    def test_invalid_api_key_returns_401(self, client: TestClient, invalid_headers: dict):
        """Wrong API key must return 401."""
        response = client.get("/jobs/", headers=invalid_headers)
        assert response.status_code == 401

    def test_valid_api_key_is_accepted(self, client: TestClient, valid_headers: dict):
        """Correct API key must be accepted (not 401/403)."""
        response = client.get("/jobs/", headers=valid_headers)
        assert response.status_code not in (401, 403)

    def test_api_key_case_sensitive(self, client: TestClient):
        """API key check is case-sensitive (wrong case → 401)."""
        response = client.get("/jobs/", headers={"X-API-Key": TEST_API_KEY.upper()})
        assert response.status_code == 401


class TestJwtAuth:
    """Tests for JWT token issuance and usage."""

    def test_get_token_with_valid_api_key(self, client: TestClient):
        """POST /auth/token with valid API key returns a JWT."""
        response = client.post("/auth/token", json={"api_key": TEST_API_KEY})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_get_token_with_invalid_api_key_returns_401(self, client: TestClient):
        """POST /auth/token with wrong key must return 401."""
        response = client.post("/auth/token", json={"api_key": "wrong-key"})
        assert response.status_code == 401

    def test_bearer_token_accepted_on_protected_endpoint(self, client: TestClient):
        """JWT token issued via /auth/token must grant access."""
        # Issue token
        token_resp = client.post("/auth/token", json={"api_key": TEST_API_KEY})
        assert token_resp.status_code == 200
        token = token_resp.json()["access_token"]

        # Use token on a protected endpoint
        response = client.get(
            "/jobs/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code not in (401, 403)

    def test_invalid_bearer_token_returns_401(self, client: TestClient):
        """A forged/expired JWT must be rejected."""
        response = client.get(
            "/jobs/",
            headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
        )
        assert response.status_code == 401

    def test_missing_body_returns_422(self, client: TestClient):
        """POST /auth/token without body must return 422 (validation error)."""
        response = client.post("/auth/token", json={})
        assert response.status_code == 422
