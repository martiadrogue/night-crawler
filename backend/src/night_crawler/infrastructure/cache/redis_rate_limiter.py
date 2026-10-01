"""Rate limits shared by every worker, kept in Redis."""

import time
from asyncio import sleep
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import limits
from limits.aio.storage import RedisStorage
from limits.aio.strategies import MovingWindowRateLimiter
from limits.errors import StorageError
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.model.value_objects import RateLimitTarget
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.rules.rate_limits import (
    penalty_after_block,
    penalty_after_success,
)
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import RedisError

DEFAULT_KEY_PREFIX = "night_crawler:rate_limit"
PENALTY_TTL_SECONDS = 86_400
"""A penalty is forgotten after a day without blocks or successes."""
MIN_WINDOW_WAIT_SECONDS = 0.01
"""The shortest wait before asking a full window again."""


class RedisRateLimiter(AbstractRateLimiter):
    """A `limits` moving window per key, plus a penalty hash per key.

    Windows live under `<prefix>:window`, penalties under
    `<prefix>:penalty:<key>` (fields `penalty` and `successes`). One
    connection pool serves both; it is bound to the event loop that
    first uses it, so each Celery task opens its own limiter.
    """

    def __init__(self, redis_url: str, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        """Connect lazily to `redis_url`, keys under `key_prefix`."""
        self._pool = ConnectionPool.from_url(redis_url)
        self._client = Redis(connection_pool=self._pool)
        self._windows = MovingWindowRateLimiter(
            RedisStorage(
                f"async+{redis_url}",
                implementation="redispy",
                key_prefix=f"{key_prefix}:window",
                wrap_exceptions=True,
                connection_pool=self._pool,
            )
        )
        self._penalty_prefix = f"{key_prefix}:penalty"

    async def acquire(self, target: RateLimitTarget) -> float:
        """Wait out the penalty, then for a slot in the window.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        with _translate_errors():
            penalty, _successes = await self._read_penalty(target)
            waited = float(penalty)
            if penalty:
                await sleep(penalty)
            window = limits.parse(target.rule.rate_limit_string)
            while not await self._windows.hit(window, target.key):
                stats = await self._windows.get_window_stats(window, target.key)
                delay = max(stats.reset_time - time.time(), MIN_WINDOW_WAIT_SECONDS)
                await sleep(delay)
                waited += delay
        return waited

    async def record_block(self, target: RateLimitTarget) -> None:
        """Add a penalty step and restart the success streak.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        await self._update_penalty(
            target,
            lambda penalty, _successes: (penalty_after_block(penalty, target.rule), 0),
        )

    async def record_success(self, target: RateLimitTarget) -> None:
        """Extend the success streak, decaying the penalty when due.

        Raises:
            ExternalServiceException: Redis is unreachable.
        """
        await self._update_penalty(
            target,
            lambda penalty, successes: penalty_after_success(
                penalty, successes, target.rule
            ),
        )

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._pool.aclose()

    async def _read_penalty(self, target: RateLimitTarget) -> tuple[int, int]:
        """Return the key's penalty seconds and success streak."""
        return _parse_penalty(
            await self._client.hmget(self._penalty_key(target), "penalty", "successes")
        )

    async def _update_penalty(
        self,
        target: RateLimitTarget,
        change: Callable[[int, int], tuple[int, int]],
    ) -> None:
        """Apply `change` to the key's penalty state atomically.

        `WATCH` retries the update if another worker changed the key in
        between, so no block or success is lost.
        """
        key = self._penalty_key(target)

        async def apply(pipe: Pipeline) -> None:
            penalty, successes = change(
                *_parse_penalty(await pipe.hmget(key, "penalty", "successes"))
            )
            pipe.multi()
            pipe.hset(key, mapping={"penalty": penalty, "successes": successes})
            pipe.expire(key, PENALTY_TTL_SECONDS)

        with _translate_errors():
            await self._client.transaction(apply, key)

    def _penalty_key(self, target: RateLimitTarget) -> str:
        """Return the Redis key of a target's penalty hash."""
        return f"{self._penalty_prefix}:{target.key}"


def _parse_penalty(values: list[bytes | None]) -> tuple[int, int]:
    """Return `(penalty, successes)` from `HMGET`, zero when unset."""
    penalty, successes = values
    return int(penalty or 0), int(successes or 0)


@contextmanager
def _translate_errors() -> Iterator[None]:
    """Turn Redis and `limits` errors into an external error."""
    try:
        yield
    except (RedisError, StorageError, OSError) as error:
        raise ExternalServiceException(
            f"The rate limiter is unavailable: {error}"
        ) from error
