import uuid

import pytest
from night_crawler.core.config import get_settings
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.infrastructure.cache.redis_auth_attempt_limiter import (
    RedisAuthAttemptLimiter,
)
from redis.asyncio import Redis


@pytest.fixture
async def limiter():
    """Use isolated Redis keys and remove them after each test."""
    prefix = f"test_auth_{uuid.uuid4().hex}"
    limiter = RedisAuthAttemptLimiter(get_settings().redis_url, key_prefix=prefix)
    yield limiter
    await limiter.aclose()
    client = Redis.from_url(get_settings().redis_url)
    async for key in client.scan_iter(f"{prefix}:*"):
        await client.delete(key)
    await client.aclose()


@pytest.mark.anyio
async def test_attempt_counter_enforces_and_clears_its_limit(limiter):
    assert not await limiter.is_limited("login:email:person@example.com", 2)

    await limiter.record_attempt("login:email:person@example.com", 900)
    assert not await limiter.is_limited("login:email:person@example.com", 2)

    await limiter.record_attempt("login:email:person@example.com", 900)
    assert await limiter.is_limited("login:email:person@example.com", 2)

    await limiter.clear("login:email:person@example.com")
    assert not await limiter.is_limited("login:email:person@example.com", 2)


@pytest.mark.anyio
async def test_an_unreachable_redis_is_an_external_error():
    limiter = RedisAuthAttemptLimiter("redis://localhost:1/0")

    with pytest.raises(ExternalServiceException):
        await limiter.is_limited("login:email:person@example.com", 5)

    await limiter.aclose()
