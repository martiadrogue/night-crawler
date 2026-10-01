"""The port for shared authentication attempt counters."""

from abc import ABC, abstractmethod


class AbstractAuthAttemptLimiter(ABC):
    """Tracks temporary limits for authentication requests."""

    @abstractmethod
    async def is_limited(self, key: str, max_attempts: int) -> bool:
        """Return whether `key` has reached its attempt limit.

        Raises:
            ExternalServiceException: the counter store is unreachable.
        """

    @abstractmethod
    async def record_attempt(self, key: str, window_seconds: int) -> None:
        """Count an attempt and start its fixed window if needed.

        Raises:
            ExternalServiceException: the counter store is unreachable.
        """

    @abstractmethod
    async def clear(self, key: str) -> None:
        """Clear a counter after successful authentication.

        Raises:
            ExternalServiceException: the counter store is unreachable.
        """
