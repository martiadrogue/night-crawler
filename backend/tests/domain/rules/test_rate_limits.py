from datetime import datetime

from night_crawler.domain.model.entities import (
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
)
from night_crawler.domain.model.value_objects import RateLimitRule, RateLimitTarget
from night_crawler.domain.rules.rate_limits import (
    penalty_after_block,
    penalty_after_success,
    resolve_rate_limit_targets,
)

NOW = datetime(2026, 1, 1)
RULE = RateLimitRule(
    rate_limit_string="5/second",
    penalty_step_seconds=10,
    max_penalty_seconds=25,
    decay_after_successes=3,
    decay_step_seconds=4,
)


def _rate_limit(rate_limit_id, rate_limit_string="5/second"):
    return MessageAidRateLimit(
        id=rate_limit_id,
        rate_limit_string=rate_limit_string,
        penalty_step_seconds=10,
        max_penalty_seconds=25,
        decay_after_successes=3,
        decay_step_seconds=4,
        created_at=NOW,
        updated_at=NOW,
    )


def _aid(**settings):
    return MessageAid(
        id="aid-1",
        message_template_id="t1",
        created_at=NOW,
        updated_at=NOW,
        **settings,
    )


def _proxy(rate_limit_id=None):
    return MessageAidProxy(
        id="proxy-1",
        url="http://proxy.example.com:8080",
        user=None,
        password="secret",
        headers={},
        created_at=NOW,
        updated_at=NOW,
        rate_limit_id=rate_limit_id,
    )


def test_the_aid_limits_the_exact_host_and_the_proxy_its_own_key():
    limits = {"r1": _rate_limit("r1"), "r2": _rate_limit("r2", "1/minute")}

    targets = resolve_rate_limit_targets(
        "https://Places.Example.com/v1/search?q=a",
        _aid(rate_limit_id="r1"),
        _proxy(rate_limit_id="r2"),
        limits,
    )

    assert (
        RateLimitTarget(key="domain:places.example.com", rule=RULE),
        RateLimitTarget(
            key="proxy:proxy-1",
            rule=RateLimitRule(
                rate_limit_string="1/minute",
                penalty_step_seconds=10,
                max_penalty_seconds=25,
                decay_after_successes=3,
                decay_step_seconds=4,
            ),
        ),
    ) == targets


def test_no_aid_no_proxy_or_a_deleted_rule_means_no_limit():
    limits = {"r1": _rate_limit("r1")}

    assert () == resolve_rate_limit_targets("https://example.com/", None, None, limits)
    assert () == resolve_rate_limit_targets(
        "https://example.com/", _aid(rate_limit_id="gone"), _proxy(), limits
    )


def test_each_block_adds_a_step_up_to_the_max():
    assert 10 == penalty_after_block(0, RULE)
    assert 20 == penalty_after_block(10, RULE)
    assert 25 == penalty_after_block(20, RULE)


def test_successes_decay_the_penalty_every_few_in_a_row():
    assert (20, 1) == penalty_after_success(20, 0, RULE)
    assert (20, 2) == penalty_after_success(20, 1, RULE)
    assert (16, 0) == penalty_after_success(20, 2, RULE)
    assert (0, 0) == penalty_after_success(3, 2, RULE)
