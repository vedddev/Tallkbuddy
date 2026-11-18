"""Tests for the health-check endpoint."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_configured_origin() -> None:
    application = create_app(Settings(cors_origins=["https://example.com"]))

    with TestClient(application) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"
