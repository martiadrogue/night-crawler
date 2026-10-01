"""Which rate limits a request waits on, and how penalties move.

A template's aid limits the exact host it calls; the proxy it goes
through limits itself. A block (a failure with one of the template's
retry codes) adds a step to the key's extra wait, up to its max; enough
successes in a row take a step off (DOMAIN_MODEL §4.8).
"""

from night_crawler.domain.model.entities import (
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
)
from night_crawler.domain.model.value_objects import RateLimitRule, RateLimitTarget
from night_crawler.domain.rules.host_session import resolve_request_host


def resolve_rate_limit_targets(
    url: str,
    aid: MessageAid | None,
    proxy: MessageAidProxy | None,
    rate_limits_by_id: dict[str, MessageAidRateLimit],
) -> tuple[RateLimitTarget, ...]:
    """Return the buckets one request waits on, domain first.

    A rule that no longer exists, or a URL without a host, limits
    nothing.
    """
    targets = (
        _domain_target(url, aid, rate_limits_by_id),
        _proxy_target(proxy, rate_limits_by_id),
    )
    return tuple(target for target in targets if None is not target)


def _domain_target(
    url: str,
    aid: MessageAid | None,
    rate_limits_by_id: dict[str, MessageAidRateLimit],
) -> RateLimitTarget | None:
    """Return the exact host's bucket, if the aid has a live rule."""
    host = resolve_request_host(url)
    rate_limit = rate_limits_by_id.get(aid.rate_limit_id) if aid else None
    if None is rate_limit or None is host:
        return None
    return RateLimitTarget(f"domain:{host}", rate_limit_rule(rate_limit))


def _proxy_target(
    proxy: MessageAidProxy | None,
    rate_limits_by_id: dict[str, MessageAidRateLimit],
) -> RateLimitTarget | None:
    """Return the proxy's bucket, if it has a live rule."""
    if None is proxy or proxy.rate_limit_id not in rate_limits_by_id:
        return None
    rate_limit = rate_limits_by_id[proxy.rate_limit_id]
    return RateLimitTarget(f"proxy:{proxy.id}", rate_limit_rule(rate_limit))


def rate_limit_rule(rate_limit: MessageAidRateLimit) -> RateLimitRule:
    """Return the rule a stored rate limit enforces."""
    return RateLimitRule(
        rate_limit_string=rate_limit.rate_limit_string,
        penalty_step_seconds=rate_limit.penalty_step_seconds,
        max_penalty_seconds=rate_limit.max_penalty_seconds,
        decay_after_successes=rate_limit.decay_after_successes,
        decay_step_seconds=rate_limit.decay_step_seconds,
    )


def penalty_after_block(penalty: int, rule: RateLimitRule) -> int:
    """Return the extra wait after a block: one step more, capped."""
    return min(penalty + rule.penalty_step_seconds, rule.max_penalty_seconds)


def penalty_after_success(
    penalty: int, successes: int, rule: RateLimitRule
) -> tuple[int, int]:
    """Return the extra wait and success streak after a success.

    Every `decay_after_successes` successes in a row take one decay
    step off the wait, never below zero, and start a new streak.
    """
    streak = successes + 1
    if streak < rule.decay_after_successes:
        return penalty, streak
    return max(penalty - rule.decay_step_seconds, 0), 0
