"""Redis-backed authentication attempt counters."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.auth_attempt_limiter import (
    AbstractAuthAttemptLimiter,
)
from redis.asyncio import Redis
from redis.exceptions import RedisError

DEFAULT_KEY_PREFIX = "night_crawler:auth_attempt"


class RedisAuthAttemptLimiter(AbstractAuthAttemptLimiter):
    """Store fixed-window counters in Redis under hashed keys."""

    def __init__(self, redis_url: str, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        """Connect lazily to `redis_url` under `key_prefix`."""
        self._client = Redis.from_url(redis_url)
        self._key_prefix = key_prefix

    async def is_limited(self, key: str, max_attempts: int) -> bool:
        """Return whether the counter reached `max_attempts`.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        with _translate_errors():
            value = await self._client.get(self._redis_key(key))
        return int(value or 0) >= max_attempts

    async def record_attempt(self, key: str, window_seconds: int) -> None:
        """Count an attempt and expire its key from the first attempt.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        with _translate_errors():
            async with self._client.pipeline(transaction=True) as pipeline:
                pipeline.incr(self._redis_key(key))
                pipeline.expire(self._redis_key(key), window_seconds, nx=True)
                await pipeline.execute()

    async def clear(self, key: str) -> None:
        """Delete the counter for `key`.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        with _translate_errors():
            await self._client.delete(self._redis_key(key))

    async def aclose(self) -> None:
        """Close the Redis connection pool."""
        await self._client.aclose()

    def _redis_key(self, key: str) -> str:
        """Return a Redis key that does not expose the identifier."""
        digest = hashlib.sha256(key.encode()).hexdigest()
        return f"{self._key_prefix}:{digest}"


@contextmanager
def _translate_errors() -> Iterator[None]:
    """Turn Redis failures into a typed external-service error."""
    try:
        yield
    except (RedisError, OSError) as error:
        raise ExternalServiceException(
            f"The auth attempt limiter is unavailable: {error}"
        ) from error
