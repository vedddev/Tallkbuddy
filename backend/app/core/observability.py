"""Small per-process operational counters and safe JSON logging context."""

from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
import json
import logging
import math
import re


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
websocket_id_context: ContextVar[str | None] = ContextVar("websocket_id", default=None)
chunk_id_context: ContextVar[int | None] = ContextVar("chunk_id", default=None)

BUCKETS_MS = (100, 250, 500, 1000, 2000, 5000, 10000, 30000, 120000)
OPERATIONS = frozenset({"http", "stt", "translation", "tts"})
SECRET_PATTERNS = (
    re.compile(r"\bgsk_[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"postgresql(?:\+asyncpg)?://[^\s]+", re.IGNORECASE),
    re.compile(r"(?:talkbuddy_session|talkbuddy_csrf|X-CSRF-Token|Ocp-Apim-Subscription-Key)=[^\s;]+", re.IGNORECASE),
)


def redact(message: str) -> str:
    for pattern in SECRET_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return message.replace("\n", " ").replace("\r", " ")[:300]


class OperationalMetrics:
    """Bounded aggregates. No user, text, URL query, or token labels."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()
        self._histograms = {name: [0] * (len(BUCKETS_MS) + 1) for name in OPERATIONS}

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in {"http_requests", "http_errors", "auth_rate_limited", "ws_connections", "ws_active", "connection_rejections", "ws_errors", "queue_overflows", "provider_timeouts", "provider_errors"}:
            raise ValueError("Unknown metric")
        with self._lock:
            self._counts[name] = max(0, self._counts[name] + amount)

    def observe(self, operation: str, duration_ms: float) -> None:
        if operation not in OPERATIONS or not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("Invalid duration metric")
        with self._lock:
            bucket = next((index for index, bound in enumerate(BUCKETS_MS) if duration_ms <= bound), len(BUCKETS_MS))
            self._histograms[operation][bucket] += 1

    def snapshot(self) -> dict[str, object]:
        """Internal use only; deliberately no public metrics route."""

        with self._lock:
            return {"counts": dict(self._counts), "buckets_ms": BUCKETS_MS,
                    "histograms": {name: tuple(values) for name, values in self._histograms.items()}}


class SafeJsonFormatter(logging.Formatter):
    """Emit fixed fields; never serialize request objects, headers, or exception args."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": redact(record.getMessage()) if record.name.startswith("app.") else "external_log",
        }
        for name, value in (
            ("request_id", request_id_context.get()),
            ("ws_id", websocket_id_context.get()),
            ("chunk_id", chunk_id_context.get()),
        ):
            if value is not None:
                data[name] = value
        for name in ("operation", "endpoint", "status", "duration_ms", "provider_category", "error_category", "queue_depth"):
            value = getattr(record, name, None)
            if isinstance(value, (str, int, float)) and len(str(value)) <= 100:
                data[name] = redact(value) if isinstance(value, str) else value
        return json.dumps(data, separators=(",", ":"), ensure_ascii=True)
