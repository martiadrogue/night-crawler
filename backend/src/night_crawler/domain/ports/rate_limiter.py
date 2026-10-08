"""The port for waiting on rate limits shared by every worker."""

from abc import ABC, abstractmethod

from night_crawler.domain.model.value_objects import RateLimitTarget


class AbstractRateLimiter(ABC):
    """Paces requests per rate-limit key, across every run at once.

    Each key holds a sliding window and an extra wait (the penalty)
    that blocks grow and successes shrink (`domain/rules/rate_limits`).
    A key can instead hold a usage budget: an amount (e.g. LLM tokens)
    counted after the fact, per fixed window of its rule's period
    (`domain/rules/llm_rate_limits`).
    """

    @abstractmethod
    async def acquire(self, target: RateLimitTarget) -> float:
        """Wait out the key's penalty and window; return seconds waited.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def try_acquire(self, target: RateLimitTarget) -> bool:
        """Take a slot in the key's window if one is free; never wait.

        For budgets too long to wait out (a day): `False` means spent.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def record_usage(self, target: RateLimitTarget, amount: int) -> None:
        """Count `amount` against the key's usage budget.

        It all counts, even past the budget: it was already used.

        Raises:
            ExternalServiceException: the limiter's store is
                unreachable.
        """

    @abstractmethod
    async def wait_for_usage(self, target: RateLimitTarget) -> float:
        """Wait while the key's usage budget is spent; return seconds.

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
