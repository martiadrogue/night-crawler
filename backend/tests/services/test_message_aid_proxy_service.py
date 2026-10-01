import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.message_aid import MessageAidCreate
from night_crawler.schemas.message_aid_proxy import (
    MessageAidProxyCreate,
    MessageAidProxyUpdate,
)
from night_crawler.services import message_aid_proxy_service, message_aid_service


@pytest.mark.anyio
async def test_create_and_update_a_proxy_without_exposing_the_password(
    write_repositories,
):
    created = await message_aid_proxy_service.create_proxy(
        write_repositories,
        MessageAidProxyCreate(url="http://proxy:8080", password="secret"),
    )

    updated = await message_aid_proxy_service.update_proxy(
        write_repositories, created.id, MessageAidProxyUpdate(user="bob")
    )

    assert "bob" == updated.user
    assert "password" not in updated.model_dump()
    saved = await write_repositories.message_aid_proxies.get_by_id(created.id)
    assert "secret" == saved.password


@pytest.mark.anyio
async def test_create_proxy_rejects_an_unknown_rate_limit(write_repositories):
    with pytest.raises(ValidationException) as exc_info:
        await message_aid_proxy_service.create_proxy(
            write_repositories,
            MessageAidProxyCreate(
                url="http://proxy:8080", password="secret", rate_limit_id="missing"
            ),
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_proxy_clears_aid_references(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    proxy = await message_aid_proxy_service.create_proxy(
        write_repositories,
        MessageAidProxyCreate(url="http://proxy:8080", password="secret"),
    )
    await message_aid_service.upsert_aid(
        write_repositories,
        member,
        draft.message_template_root_id,
        MessageAidCreate(selected_proxy_id=proxy.id),
    )

    await message_aid_proxy_service.delete_proxy(write_repositories, proxy.id)

    aid = await write_repositories.message_aids.get_by_message_template_id(
        draft.message_template_root_id
    )
    assert None is aid.selected_proxy_id
    assert None is await write_repositories.message_aid_proxies.get_by_id(proxy.id)
