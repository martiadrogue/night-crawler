import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.message_aid import MessageAidCreate
from night_crawler.schemas.message_aid_proxy import MessageAidProxyCreate
from night_crawler.services import message_aid_proxy_service, message_aid_service


async def _root_template_id(write_repositories, create_crawler) -> str:
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return draft.message_template_root_id


@pytest.mark.anyio
async def test_upsert_aid_creates_then_replaces_in_place(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)

    created = await message_aid_service.upsert_aid(
        write_repositories, member, template_id, MessageAidCreate(render_mode="stealth")
    )
    replaced = await message_aid_service.upsert_aid(
        write_repositories, member, template_id, MessageAidCreate(ttl=30)
    )

    assert created.id == replaced.id
    assert "none" == replaced.render_mode
    assert 30 == replaced.ttl


@pytest.mark.anyio
async def test_upsert_aid_accepts_a_known_proxy(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    proxy = await message_aid_proxy_service.create_proxy(
        write_repositories,
        MessageAidProxyCreate(url="http://proxy:8080", password="secret"),
    )

    aid = await message_aid_service.upsert_aid(
        write_repositories,
        member,
        template_id,
        MessageAidCreate(selected_proxy_id=proxy.id),
    )

    assert proxy.id == aid.selected_proxy_id


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["selected_proxy_id", "rate_limit_id"])
async def test_upsert_aid_rejects_unknown_references(
    write_repositories, member, create_crawler, field
):
    template_id = await _root_template_id(write_repositories, create_crawler)

    with pytest.raises(ValidationException) as exc_info:
        await message_aid_service.upsert_aid(
            write_repositories,
            member,
            template_id,
            MessageAidCreate(**{field: "missing"}),
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_aid_removes_it(write_repositories, member, create_crawler):
    template_id = await _root_template_id(write_repositories, create_crawler)
    await message_aid_service.upsert_aid(
        write_repositories, member, template_id, MessageAidCreate()
    )

    await message_aid_service.delete_aid(write_repositories, member, template_id)

    with pytest.raises(ValidationException) as exc_info:
        await message_aid_service.get_aid(write_repositories, member, template_id)
    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_an_aid_keeps_its_success_codes(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)

    plain = await message_aid_service.upsert_aid(
        write_repositories, member, template_id, MessageAidCreate()
    )
    custom = await message_aid_service.upsert_aid(
        write_repositories,
        member,
        template_id,
        MessageAidCreate(success_codes=["200", "404"]),
    )
    stored = await message_aid_service.get_aid(write_repositories, member, template_id)

    assert None is plain.success_codes
    assert ["200", "404"] == custom.success_codes == stored.success_codes


@pytest.mark.anyio
async def test_an_aid_has_no_proxy_rotation_settings(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)

    aid = await message_aid_service.upsert_aid(
        write_repositories, member, template_id, MessageAidCreate(max_retry_attempts=2)
    )

    assert {"ban_codes", "max_rotating_retries"}.isdisjoint(aid.model_dump())
    assert 2 == aid.max_retry_attempts
