"""Rate limiter decorator adding OpenTelemetry metrics and spans."""

from night_crawler.domain.model.value_objects import RateLimitTarget
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer


class OpenTelemetryRateLimiter(AbstractRateLimiter):
    """Measures how long runs wait on each rate-limit key.

    Every `acquire` is one `crawler rate limit` span, so a trace shows
    the wait before each request; the seconds waited add up in
    `crawler_rate_limit_wait_seconds_total` and blocks in
    `crawler_rate_limit_blocks_total`, both labelled by `key`.
    """

    def __init__(
        self, rate_limiter: AbstractRateLimiter, meter: Meter, tracer: Tracer
    ) -> None:
        """Wrap `rate_limiter`."""
        self._rate_limiter = rate_limiter
        self._tracer = tracer
        self._wait = meter.create_counter(
            "crawler.rate_limit.wait",
            unit="s",
            description="Seconds runs waited on rate limits.",
        )
        self._blocks = meter.create_counter(
            "crawler.rate_limit.blocks",
            description="Blocked requests that grew a key's penalty.",
        )

    async def acquire(self, target: RateLimitTarget) -> float:
        """Wait through the wrapped limiter, measured.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        with self._tracer.start_as_current_span(
            "crawler rate limit",
            attributes={"night_crawler.rate_limit.key": target.key},
        ) as span:
            waited = await self._rate_limiter.acquire(target)
            span.set_attribute("night_crawler.rate_limit.waited_seconds", waited)
        self._wait.add(waited, {"key": target.key})
        return waited

    async def try_acquire(self, target: RateLimitTarget) -> bool:
        """Take a free slot through the wrapped limiter, if any.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        return await self._rate_limiter.try_acquire(target)

    async def record_usage(self, target: RateLimitTarget, amount: int) -> None:
        """Count usage through the wrapped limiter.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        await self._rate_limiter.record_usage(target, amount)

    async def wait_for_usage(self, target: RateLimitTarget) -> float:
        """Wait out a spent usage budget, adding the seconds waited.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        waited = await self._rate_limiter.wait_for_usage(target)
        self._wait.add(waited, {"key": target.key})
        return waited

    async def record_block(self, target: RateLimitTarget) -> None:
        """Count the block and grow the key's penalty.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        self._blocks.add(1, {"key": target.key})
        await self._rate_limiter.record_block(target)

    async def record_success(self, target: RateLimitTarget) -> None:
        """Count a success toward shrinking the key's penalty.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """
        await self._rate_limiter.record_success(target)

    async def aclose(self) -> None:
        """Release the wrapped limiter's connection."""
        await self._rate_limiter.aclose()
