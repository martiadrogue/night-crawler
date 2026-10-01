import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.message_aid import MessageAidCreate
from night_crawler.schemas.message_selector import MessageSelectorCreate
from night_crawler.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateUpdate,
)
from night_crawler.services import (
    message_aid_service,
    message_selector_service,
    message_template_service,
)


async def _draft(write_repositories, create_crawler):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return draft


@pytest.mark.anyio
async def test_create_and_update_a_template(write_repositories, member, create_crawler):
    draft = await _draft(write_repositories, create_crawler)

    created = await message_template_service.create_template(
        write_repositories,
        member,
        draft.id,
        MessageTemplateCreate(action="GET", url="https://example.com/{{page}}"),
    )
    updated = await message_template_service.update_template(
        write_repositories, member, created.id, MessageTemplateUpdate(action="POST")
    )

    assert draft.id == created.crawler_version_id
    assert "POST" == updated.action
    assert "https://example.com/{{page}}" == updated.url
    templates = await message_template_service.get_templates(
        write_repositories, member, draft.id
    )
    assert 2 == len(templates)


@pytest.mark.anyio
async def test_delete_template_refuses_the_root(
    write_repositories, member, create_crawler
):
    draft = await _draft(write_repositories, create_crawler)

    with pytest.raises(ValidationException) as exc_info:
        await message_template_service.delete_template(
            write_repositories, member, draft.message_template_root_id
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_template_removes_its_selectors_and_aid(
    write_repositories, member, create_crawler
):
    draft = await _draft(write_repositories, create_crawler)
    template = await message_template_service.create_template(
        write_repositories,
        member,
        draft.id,
        MessageTemplateCreate(action="GET", url="u"),
    )
    selector = await message_selector_service.create_selector(
        write_repositories,
        member,
        template.id,
        MessageSelectorCreate(path="//a", type="value"),
    )
    await message_aid_service.upsert_aid(
        write_repositories, member, template.id, MessageAidCreate()
    )

    await message_template_service.delete_template(
        write_repositories, member, template.id
    )

    assert None is await write_repositories.message_templates.get_by_id(template.id)
    assert None is await write_repositories.message_selectors.get_by_id(selector.id)
    assert None is await write_repositories.message_aids.get_by_message_template_id(
        template.id
    )


@pytest.mark.anyio
async def test_get_template_raises_when_missing(write_repositories, member):
    with pytest.raises(ValidationException) as exc_info:
        await message_template_service.get_template(
            write_repositories, member, "missing"
        )

    assert 404 == exc_info.value.status_code
