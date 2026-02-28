"""
Integration tests for health check endpoints.
"""
import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for /health, /health/live, /health/ready."""

    def test_liveness_probe_returns_200(self, client: TestClient):
        """Kubernetes liveness probe must always return 200."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_readiness_probe_returns_200_or_503(self, client: TestClient):
        """Readiness probe returns 200 when deps OK, 503 when not."""
        response = client.get("/health/ready")
        # In test environment external services are mocked; expect either outcome
        assert response.status_code in (200, 503)

    def test_health_full_has_services_key(self, client: TestClient):
        """Full health check response contains a 'services' list."""
        response = client.get("/health")
        assert response.status_code in (200, 503)
        data = response.json()
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_health_full_includes_postgres(self, client: TestClient):
        """Health check must report PostgreSQL status."""
        response = client.get("/health")
        data = response.json()
        service_names = [s["name"] for s in data.get("services", [])]
        assert "postgresql" in service_names

    def test_root_endpoint(self, client: TestClient):
        """Root endpoint returns API name and version."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data

    def test_metrics_endpoint(self, client: TestClient):
        """Prometheus /metrics endpoint returns text/plain."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
