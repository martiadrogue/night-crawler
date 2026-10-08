"""The rate limits every call to a hosted LLM waits on.

A provider's quota (e.g. Gemini's free tier) is per project and model,
not per worker, so one budget per model is kept in the shared limiter
under `llm:<model>` keys (DOMAIN_MODEL §4.8):

- `:minute`, requests per minute, waited on before each call; a
  rate-limited call (HTTP 429) grows its penalty, successes decay it;
- `:day`, requests per day, never waited on: once spent, calls fail;
- `:tokens`, tokens per minute, counted after each call and waited on
  before the next one once spent.
"""

from dataclasses import dataclass

from night_crawler.domain.model.value_objects import RateLimitRule, RateLimitTarget

PENALTY_STEP_SECONDS = 10
"""Extra wait each rate-limited call adds to the minute key."""

MAX_PENALTY_SECONDS = 60
"""The most that extra wait grows to: one minute window."""

DECAY_AFTER_SUCCESSES = 5
"""Successful calls in a row that take a penalty step off."""


@dataclass(frozen=True)
class LlmBudget:
    """A model's quota, as the provider grants it.

    Attributes:
        requests_per_minute: Calls per minute.
        requests_per_day: Calls per day.
        tokens_per_minute: Tokens (prompt and output) per minute.
    """

    requests_per_minute: int
    requests_per_day: int
    tokens_per_minute: int


@dataclass(frozen=True)
class LlmRateLimitTargets:
    """The buckets one model's calls wait on.

    Attributes:
        key: `llm:<model>`, the model's whole budget, as measured.
        minute: Requests per minute, with a penalty.
        day: Requests per day.
        tokens: Tokens per minute, a usage budget.
    """

    key: str
    minute: RateLimitTarget
    day: RateLimitTarget
    tokens: RateLimitTarget


def resolve_llm_rate_limit_targets(
    model: str, budget: LlmBudget
) -> LlmRateLimitTargets:
    """Return the buckets every call to `model` waits on."""
    key = f"llm:{model}"
    return LlmRateLimitTargets(
        key=key,
        minute=RateLimitTarget(
            f"{key}:minute",
            RateLimitRule(
                rate_limit_string=f"{budget.requests_per_minute}/minute",
                penalty_step_seconds=PENALTY_STEP_SECONDS,
                max_penalty_seconds=MAX_PENALTY_SECONDS,
                decay_after_successes=DECAY_AFTER_SUCCESSES,
                decay_step_seconds=PENALTY_STEP_SECONDS,
            ),
        ),
        day=_unpenalized(f"{key}:day", f"{budget.requests_per_day}/day"),
        tokens=_unpenalized(f"{key}:tokens", f"{budget.tokens_per_minute}/minute"),
    )


def _unpenalized(key: str, rate_limit_string: str) -> RateLimitTarget:
    """Return a bucket that only counts: blocks never add a wait."""
    return RateLimitTarget(
        key,
        RateLimitRule(
            rate_limit_string=rate_limit_string,
            penalty_step_seconds=0,
            max_penalty_seconds=0,
            decay_after_successes=1,
            decay_step_seconds=0,
        ),
    )
