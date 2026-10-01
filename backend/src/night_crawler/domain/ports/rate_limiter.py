"""The port for waiting on rate limits shared by every worker."""

from abc import ABC, abstractmethod

from night_crawler.domain.model.value_objects import RateLimitTarget


class AbstractRateLimiter(ABC):
    """Paces requests per rate-limit key, across every run at once.

    Each key holds a sliding window and an extra wait (the penalty)
    that blocks grow and successes shrink (`domain/rules/rate_limits`).
    """

    @abstractmethod
    async def acquire(self, target: RateLimitTarget) -> float:
        """Wait out the key's penalty and window; return seconds waited.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def record_block(self, target: RateLimitTarget) -> None:
        """Grow the key's penalty after a blocked request.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def record_success(self, target: RateLimitTarget) -> None:
        """Count a success toward shrinking the key's penalty.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release the connection pooled across one run."""
