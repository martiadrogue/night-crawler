from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import (
    MessageAid,
    MessageAidProxy,
    MessageAidRateLimit,
)

NOW = datetime(2026, 1, 1)


def _rate_limit(**overrides) -> MessageAidRateLimit:
    defaults = {
        "id": "rate-limit-1",
        "name": "Default proxy limit",
        "rate_limit_string": "100/minute",
        "penalty_step_seconds": 5,
        "max_penalty_seconds": 60,
        "decay_after_successes": 3,
        "decay_step_seconds": 5,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return MessageAidRateLimit(**{**defaults, **overrides})


@pytest.mark.anyio
async def test_save_persists_and_returns_domain_entity(write_repositories):
    saved = await write_repositories.message_aid_rate_limits.save(_rate_limit())

    assert "rate-limit-1" == saved.id
    assert "100/minute" == saved.rate_limit_string
    assert 60 == saved.max_penalty_seconds


@pytest.mark.anyio
async def test_save_upserts_the_existing_document(write_repositories):
    repository = write_repositories.message_aid_rate_limits
    await repository.save(_rate_limit())

    updated = await repository.save(_rate_limit(rate_limit_string="200/minute"))

    assert "200/minute" == updated.rate_limit_string
    assert 1 == len(await repository.get_all())


@pytest.mark.anyio
async def test_save_rejects_an_invalid_rate_limit_string(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await write_repositories.message_aid_rate_limits.save(
            _rate_limit(rate_limit_string="garbage")
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_the_collection_validator_rejects_negative_steps(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await write_repositories.message_aid_rate_limits.save(
            _rate_limit(penalty_step_seconds=-1)
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_clearing_a_rate_limit_nulls_aid_and_proxy_references(write_repositories):
    await write_repositories.message_aid_rate_limits.save(_rate_limit())
    await write_repositories.message_aids.save(
        MessageAid(
            id="aid-1",
            message_template_id="template-1",
            rate_limit_id="rate-limit-1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await write_repositories.message_aid_proxies.save(
        MessageAidProxy(
            id="proxy-1",
            url="http://proxy:8080",
            user=None,
            password="secret",
            headers={},
            rate_limit_id="rate-limit-1",
            created_at=NOW,
            updated_at=NOW,
        )
    )

    await write_repositories.message_aids.clear_rate_limit_id("rate-limit-1")
    await write_repositories.message_aid_proxies.clear_rate_limit_id("rate-limit-1")

    aid = await write_repositories.message_aids.get_by_message_template_id("template-1")
    proxy = await write_repositories.message_aid_proxies.get_by_id("proxy-1")
    assert None is aid.rate_limit_id
    assert None is proxy.rate_limit_id
