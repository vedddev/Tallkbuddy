"""Safe logs and bounded operational measurements."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.observability import OperationalMetrics, SafeJsonFormatter, request_id_context
from app.main import create_app


def test_json_log_redacts_secrets_and_omits_unapproved_fields() -> None:
    formatter = SafeJsonFormatter()
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1,
        "request gsk_testsecret123 postgresql+asyncpg://user:password@host/db",
        (), None,
    )
    record.endpoint = "talkbuddy_session=private"
    record.private_text = "private transcript"
    token = request_id_context.set("correlation-only")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        request_id_context.reset(token)
    encoded = json.dumps(payload)
    assert payload["request_id"] == "correlation-only"
    assert "private" not in encoded
    assert "testsecret" not in encoded
    assert "password" not in encoded
    assert "REDACTED" in encoded


def test_operational_metrics_have_fixed_names_and_bounded_buckets() -> None:
    metrics = OperationalMetrics()
    metrics.increment("http_requests")
    metrics.observe("stt", 10_000_000)
    snapshot = metrics.snapshot()
    assert snapshot["counts"] == {"http_requests": 1}
    assert snapshot["histograms"]["stt"][-1] == 1
    with pytest.raises(ValueError):
        metrics.increment("user_email")
    with pytest.raises(ValueError):
        metrics.observe("stt", float("nan"))


def test_http_request_id_and_internal_metrics_without_public_route() -> None:
    application = create_app(Settings(_env_file=None, app_env="test", database_url=None))
    with TestClient(application) as client:
        success = client.get("/api/health")
        failure = client.get("/api/does-not-exist")
        private_metrics = client.get("/api/metrics")
    assert success.status_code == 200
    assert len(success.headers["X-Request-ID"]) == 32
    assert failure.status_code == 404
    assert private_metrics.status_code == 404
    counts = application.state.metrics.snapshot()["counts"]
    assert counts["http_requests"] == 3
    assert counts["http_errors"] == 2
