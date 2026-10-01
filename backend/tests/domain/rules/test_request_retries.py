from datetime import datetime

from night_crawler.domain.model.entities import MessageAid
from night_crawler.domain.rules.request_retries import (
    retry_delay_seconds,
    retry_policy_for,
    should_retry,
)

NOW = datetime(2026, 1, 1)


def _aid(**settings):
    return MessageAid(
        id="aid-1", message_template_id="t1", created_at=NOW, updated_at=NOW, **settings
    )


def test_without_an_aid_the_defaults_apply():
    policy = retry_policy_for(None)

    assert ("429", "500", "502", "503", "504") == policy.retry_codes
    assert 3 == policy.max_retries


def test_an_aid_sets_its_own_codes_and_attempts():
    policy = retry_policy_for(
        _aid(retry_codes=["503", "timeout"], max_retry_attempts=1)
    )

    assert ("503", "timeout") == policy.retry_codes
    assert 1 == policy.max_retries


def test_only_retry_codes_are_retried_until_the_attempts_run_out():
    policy = retry_policy_for(
        _aid(retry_codes=["503", "timeout"], max_retry_attempts=2)
    )

    assert should_retry(policy, "503", retries_done=0)
    assert should_retry(policy, "timeout", retries_done=1)
    assert not should_retry(policy, "503", retries_done=2)
    assert not should_retry(policy, "404", retries_done=0)
    assert not should_retry(policy, None, retries_done=0)


def test_zero_attempts_never_retry():
    policy = retry_policy_for(_aid(max_retry_attempts=0))

    assert not should_retry(policy, "503", retries_done=0)


def test_the_wait_doubles_up_to_a_cap():
    assert [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0] == [
        retry_delay_seconds(retry) for retry in range(1, 8)
    ]
