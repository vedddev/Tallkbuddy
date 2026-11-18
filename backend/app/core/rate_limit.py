"""Small per-process sliding-window limiter for authentication requests."""

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._checks = 0

    def retry_after(self, key: str) -> int | None:
        """Record an attempt, or return seconds until the oldest attempt expires."""

        now = monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % 1000 == 0:
                for old_key, old_attempts in list(self._attempts.items()):
                    if not old_attempts or old_attempts[-1] <= now - self.window_seconds:
                        del self._attempts[old_key]
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return max(1, int(attempts[0] + self.window_seconds - now) + 1)
            attempts.append(now)
            return None
