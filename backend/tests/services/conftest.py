"""Service tests share repository and port fakes."""

import pytest
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)


class RecordingAuthAttemptLimiter(AbstractAuthAttemptLimiter):
    """Store auth attempt counters in memory."""

    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}

    async def is_limited(self, key: str, max_attempts: int) -> bool:
        return self.attempts.get(key, 0) >= max_attempts

    async def record_attempt(self, key: str, window_seconds: int) -> None:
        self.attempts[key] = self.attempts.get(key, 0) + 1

    async def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


@pytest.fixture
def auth_attempt_limiter() -> RecordingAuthAttemptLimiter:
    return RecordingAuthAttemptLimiter()
