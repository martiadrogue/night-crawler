import uuid

import pytest
from night_crawler.core.config import get_settings
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.model.value_objects import RateLimitRule, RateLimitTarget
from night_crawler.infrastructure.cache import redis_rate_limiter
from night_crawler.infrastructure.cache.redis_rate_limiter import RedisRateLimiter
from redis.asyncio import Redis


def _target(rate_limit_string="100/second", step=10, max_penalty=25):
    return RateLimitTarget(
        key="domain:example.com",
        rule=RateLimitRule(
            rate_limit_string=rate_limit_string,
            penalty_step_seconds=step,
            max_penalty_seconds=max_penalty,
            decay_after_successes=3,
            decay_step_seconds=4,
        ),
    )


@pytest.fixture
async def limiter():
    """A limiter on keys of its own, deleted afterwards."""
    prefix = f"test_{uuid.uuid4().hex}"
    limiter = RedisRateLimiter(get_settings().redis_url, key_prefix=prefix)
    yield limiter
    await limiter.aclose()
    client = Redis.from_url(get_settings().redis_url)
    async for key in client.scan_iter(f"{prefix}*"):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
def waits(monkeypatch):
    """Record the limiter's penalty waits instead of sleeping."""
    recorded = []

    async def record(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(redis_rate_limiter, "sleep", record)
    return recorded


@pytest.mark.anyio
async def test_requests_wait_once_the_window_is_full(limiter):
    target = _target("2/second")

    first = await limiter.acquire(target)
    second = await limiter.acquire(target)
    third = await limiter.acquire(target)

    assert (0.0, 0.0) == (first, second)
    assert 0.0 < third < 1.5


@pytest.mark.anyio
async def test_blocks_add_a_penalty_wait_up_to_the_max(limiter, waits):
    target = _target()
    for _ in range(3):
        await limiter.record_block(target)

    waited = await limiter.acquire(target)

    assert [25] == waits
    assert 25.0 == waited


@pytest.mark.anyio
async def test_successes_in_a_row_decay_the_penalty(limiter, waits):
    target = _target()
    await limiter.record_block(target)
    await limiter.record_block(target)
    for _ in range(3):
        await limiter.record_success(target)

    await limiter.acquire(target)

    assert [16] == waits


@pytest.mark.anyio
async def test_an_unreachable_redis_is_an_external_error():
    limiter = RedisRateLimiter("redis://localhost:1/0", key_prefix="unused")

    with pytest.raises(ExternalServiceException):
        await limiter.acquire(_target())

    await limiter.aclose()
