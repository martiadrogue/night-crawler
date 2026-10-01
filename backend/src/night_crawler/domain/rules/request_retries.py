"""When a failed crawl request is sent again, and how long to wait.

A failure whose code is one of the template's retry codes is retried,
up to its retry attempts; only then does the request count as failed
(DOMAIN_MODEL §4.6).
"""

from dataclasses import dataclass

from night_crawler.domain.model.constants import (
    DEFAULT_MAX_RETRY_ATTEMPTS,
    DEFAULT_RETRY_CODES,
)
from night_crawler.domain.model.entities import MessageAid

MAX_RETRY_DELAY_SECONDS = 30.0
"""The longest wait before a retry, however many came before."""


@dataclass(frozen=True)
class RetryPolicy:
    """What a template retries, and how many times.

    Attributes:
        retry_codes: Failure codes worth another try.
        max_retries: Retries after the first try; 0 never retries.
    """

    retry_codes: tuple[str, ...]
    max_retries: int


def retry_policy_for(aid: MessageAid | None) -> RetryPolicy:
    """Return a template's retry policy; unset settings use defaults."""
    retry_codes = (
        DEFAULT_RETRY_CODES
        if None is aid or None is aid.retry_codes
        else aid.retry_codes
    )
    max_retries = (
        DEFAULT_MAX_RETRY_ATTEMPTS
        if None is aid or None is aid.max_retry_attempts
        else aid.max_retry_attempts
    )
    return RetryPolicy(retry_codes=tuple(retry_codes), max_retries=max_retries)


def should_retry(
    policy: RetryPolicy, failure_code: str | None, *, retries_done: int
) -> bool:
    """Tell whether to retry a failure after `retries_done` retries."""
    return failure_code in policy.retry_codes and retries_done < policy.max_retries


def retry_delay_seconds(retry: int) -> float:
    """Return the wait before retry number `retry` (1 is the first).

    It doubles each time, from one second up to
    `MAX_RETRY_DELAY_SECONDS`.
    """
    return min(2.0 ** (retry - 1), MAX_RETRY_DELAY_SECONDS)
