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
def prefix() -> str:
    return f"test_{uuid.uuid4().hex}"


async def _delete_keys(pattern: str) -> None:
    client = Redis.from_url(get_settings().redis_url)
    async for key in client.scan_iter(pattern):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
async def limiter(prefix):
    """A limiter on keys of its own, deleted afterwards."""
    limiter = RedisRateLimiter(get_settings().redis_url, key_prefix=prefix)
    yield limiter
    await limiter.aclose()
    await _delete_keys(f"{prefix}*")


@pytest.fixture
def waits(monkeypatch, prefix):
    """Record the limiter's waits instead of sleeping.

    A recorded wait clears the limiter's usage windows, as the real
    wait would let them reset.
    """
    recorded = []

    async def record(seconds):
        recorded.append(seconds)
        await _delete_keys(f"{prefix}:usage*")

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


@pytest.mark.anyio
async def test_try_acquire_takes_a_free_slot_and_never_waits(limiter, waits):
    target = _target("2/day")

    taken = [await limiter.try_acquire(target) for _ in range(3)]

    assert [True, True, False] == taken
    assert [] == waits


@pytest.mark.anyio
async def test_usage_under_its_budget_does_not_wait(limiter, waits):
    target = _target("1000/minute")
    await limiter.record_usage(target, 400)

    assert 0.0 == await limiter.wait_for_usage(target)
    assert [] == waits


@pytest.mark.anyio
async def test_spent_usage_waits_for_its_window_to_reset(limiter, waits):
    target = _target("1000/minute")
    await limiter.record_usage(target, 700)
    # One call's tokens may overshoot the budget: they still all count.
    await limiter.record_usage(target, 700)

    waited = await limiter.wait_for_usage(target)

    [wait] = waits
    assert 0.0 < wait <= 60.0
    assert wait == waited
