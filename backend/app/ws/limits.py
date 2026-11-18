"""Per-process concurrent WebSocket connection limits."""

import asyncio
from collections import defaultdict
from uuid import UUID


class ConnectionRegistry:
    def __init__(self, max_per_user: int) -> None:
        self.max_per_user = max_per_user
        self._counts: dict[UUID, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: UUID) -> bool:
        async with self._lock:
            if self._counts[user_id] >= self.max_per_user:
                return False
            self._counts[user_id] += 1
            return True

    async def release(self, user_id: UUID) -> None:
        async with self._lock:
            count = self._counts.get(user_id, 0)
            if count <= 1:
                self._counts.pop(user_id, None)
            else:
                self._counts[user_id] = count - 1
