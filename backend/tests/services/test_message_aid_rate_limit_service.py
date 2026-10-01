import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.message_aid_proxy import MessageAidProxyCreate
from night_crawler.schemas.message_aid_rate_limit import (
    MessageAidRateLimitCreate,
    MessageAidRateLimitUpdate,
)
from night_crawler.services import (
    message_aid_proxy_service,
    message_aid_rate_limit_service,
)


@pytest.mark.anyio
async def test_create_and_update_a_rate_limit(write_repositories):
    created = await message_aid_rate_limit_service.create_rate_limit(
        write_repositories, MessageAidRateLimitCreate(rate_limit_string="10/second")
    )

    updated = await message_aid_rate_limit_service.update_rate_limit(
        write_repositories, created.id, MessageAidRateLimitUpdate(name="Slow")
    )

    assert "Slow" == updated.name
    assert "10/second" == updated.rate_limit_string


@pytest.mark.anyio
async def test_create_rate_limit_rejects_an_invalid_rate_limit_string(
    write_repositories,
):
    with pytest.raises(ValidationException) as exc_info:
        await message_aid_rate_limit_service.create_rate_limit(
            write_repositories, MessageAidRateLimitCreate(rate_limit_string="garbage")
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_rate_limit_raises_when_missing(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await message_aid_rate_limit_service.update_rate_limit(
            write_repositories, "missing", MessageAidRateLimitUpdate(name="x")
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_rate_limit_clears_proxy_references(write_repositories):
    rate_limit = await message_aid_rate_limit_service.create_rate_limit(
        write_repositories, MessageAidRateLimitCreate(rate_limit_string="10/second")
    )
    proxy = await message_aid_proxy_service.create_proxy(
        write_repositories,
        MessageAidProxyCreate(
            url="http://proxy:8080", password="secret", rate_limit_id=rate_limit.id
        ),
    )

    await message_aid_rate_limit_service.delete_rate_limit(
        write_repositories, rate_limit.id
    )

    saved = await write_repositories.message_aid_proxies.get_by_id(proxy.id)
    assert None is saved.rate_limit_id
