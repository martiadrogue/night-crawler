from unittest.mock import create_autospec

import pytest
from night_crawler.domain.model.value_objects import RateLimitRule, RateLimitTarget
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.infrastructure.telemetry.open_telemetry_rate_limiter import (
    OpenTelemetryRateLimiter,
)

TARGET = RateLimitTarget(
    key="domain:example.com",
    rule=RateLimitRule(
        rate_limit_string="5/second",
        penalty_step_seconds=10,
        max_penalty_seconds=25,
        decay_after_successes=3,
        decay_step_seconds=4,
    ),
)


def _limiter(meter, tracer, waited=0.0):
    inner = create_autospec(AbstractRateLimiter, instance=True)
    inner.acquire.return_value = waited
    return inner, OpenTelemetryRateLimiter(inner, meter, tracer)


@pytest.mark.anyio
async def test_adds_the_seconds_waited_by_key(meter, tracer, read_points):
    inner, limiter = _limiter(meter, tracer, waited=1.5)

    assert 1.5 == await limiter.acquire(TARGET)

    inner.acquire.assert_awaited_once_with(TARGET)
    [(attributes, point)] = read_points("crawler.rate_limit.wait")
    assert {"key": "domain:example.com"} == attributes
    assert 1.5 == point.value


@pytest.mark.anyio
async def test_traces_each_acquire_with_its_wait(meter, tracer, span_exporter):
    _, limiter = _limiter(meter, tracer, waited=2.0)

    await limiter.acquire(TARGET)

    [span] = span_exporter.get_finished_spans()
    assert "crawler rate limit" == span.name
    assert "domain:example.com" == span.attributes["night_crawler.rate_limit.key"]
    assert 2.0 == span.attributes["night_crawler.rate_limit.waited_seconds"]


@pytest.mark.anyio
async def test_counts_blocks_by_key(meter, tracer, read_points):
    inner, limiter = _limiter(meter, tracer)

    await limiter.record_block(TARGET)
    await limiter.record_block(TARGET)

    assert 2 == inner.record_block.await_count
    [(attributes, point)] = read_points("crawler.rate_limit.blocks")
    assert {"key": "domain:example.com"} == attributes
    assert 2 == point.value


@pytest.mark.anyio
async def test_passes_successes_and_close_through(meter, tracer):
    inner, limiter = _limiter(meter, tracer)

    await limiter.record_success(TARGET)
    await limiter.aclose()

    inner.record_success.assert_awaited_once_with(TARGET)
    inner.aclose.assert_awaited_once_with()


@pytest.mark.anyio
async def test_usage_and_slot_calls_pass_through_and_waits_add_up(
    meter, tracer, read_points
):
    inner, limiter = _limiter(meter, tracer)
    inner.try_acquire.return_value = False
    inner.wait_for_usage.return_value = 2.0

    assert not await limiter.try_acquire(TARGET)
    await limiter.record_usage(TARGET, 120)
    assert 2.0 == await limiter.wait_for_usage(TARGET)

    inner.try_acquire.assert_awaited_once_with(TARGET)
    inner.record_usage.assert_awaited_once_with(TARGET, 120)
    [(attributes, point)] = read_points("crawler.rate_limit.wait")
    assert {"key": "domain:example.com"} == attributes
    assert 2.0 == point.value
