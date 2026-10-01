import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.schemas.message_selector import (
    MessageSelectorCreate,
    MessageSelectorUpdate,
)
from night_crawler.schemas.message_template import MessageTemplateCreate
from night_crawler.services import (
    crawler_version_service,
    message_selector_service,
    message_template_service,
)


async def _root_template_id(write_repositories, create_crawler) -> str:
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return draft.message_template_root_id


async def _selector(write_repositories, member, template_id, parent_id=None):
    return await message_selector_service.create_selector(
        write_repositories,
        member,
        template_id,
        MessageSelectorCreate(
            path="//div", type="iterator", parent_selector_id=parent_id
        ),
    )


@pytest.mark.anyio
async def test_create_selector_under_a_parent(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    parent = await _selector(write_repositories, member, template_id)

    child = await _selector(write_repositories, member, template_id, parent.id)

    assert parent.id == child.parent_selector_id
    assert template_id == child.message_template_id


@pytest.mark.anyio
async def test_create_selector_rejects_a_parent_on_another_template(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    parent = await _selector(write_repositories, member, template_id)
    template = await write_repositories.message_templates.get_by_id(template_id)
    other = await message_template_service.create_template(
        write_repositories,
        member,
        template.crawler_version_id,
        MessageTemplateCreate(action="GET", url="u"),
    )

    with pytest.raises(ValidationException) as exc_info:
        await _selector(write_repositories, member, other.id, parent.id)

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_selector_refuses_a_parent_cycle(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    parent = await _selector(write_repositories, member, template_id)
    child = await _selector(write_repositories, member, template_id, parent.id)

    with pytest.raises(ValidationException) as exc_info:
        await message_selector_service.update_selector(
            write_repositories,
            member,
            parent.id,
            MessageSelectorUpdate(parent_selector_id=child.id),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_selector_requires_config_for_pagination(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    selector = await _selector(write_repositories, member, template_id)

    with pytest.raises(ValidationException) as exc_info:
        await message_selector_service.update_selector(
            write_repositories,
            member,
            selector.id,
            MessageSelectorUpdate(type="pagination"),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_selector_removes_its_subtree(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    parent = await _selector(write_repositories, member, template_id)
    child = await _selector(write_repositories, member, template_id, parent.id)
    sibling = await _selector(write_repositories, member, template_id)

    await message_selector_service.delete_selector(
        write_repositories, member, parent.id
    )

    remaining = await message_selector_service.get_selectors(
        write_repositories, member, template_id
    )
    assert [sibling.id] == [selector.id for selector in remaining]
    assert None is await write_repositories.message_selectors.get_by_id(child.id)


@pytest.mark.anyio
async def test_editing_a_published_selector_lands_on_the_fork(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    selector = await _selector(write_repositories, member, template_id)
    template = await write_repositories.message_templates.get_by_id(template_id)
    version = await write_repositories.crawler_versions.get_by_id(
        template.crawler_version_id
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, version.crawler_id, version.id
    )

    edited = await message_selector_service.update_selector(
        write_repositories, member, selector.id, MessageSelectorUpdate(path="//span")
    )

    assert selector.id != edited.id
    assert "//span" == edited.path
    original = await write_repositories.message_selectors.get_by_id(selector.id)
    assert "//div" == original.path


@pytest.mark.anyio
async def test_a_context_selector_reads_a_placeholder(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)

    selector = await message_selector_service.create_selector(
        write_repositories,
        member,
        template_id,
        MessageSelectorCreate(
            path="place_id", type="value", source="context", title="item_id"
        ),
    )

    assert ("context", "place_id") == (selector.source, selector.path)


@pytest.mark.anyio
async def test_only_value_and_boolean_selectors_read_the_context(
    write_repositories, member, create_crawler
):
    template_id = await _root_template_id(write_repositories, create_crawler)
    selector = await _selector(write_repositories, member, template_id)

    with pytest.raises(ValidationException) as exc_info:
        await message_selector_service.update_selector(
            write_repositories,
            member,
            selector.id,
            MessageSelectorUpdate(source="context"),
        )

    assert 400 == exc_info.value.status_code
    assert "context" in exc_info.value.message
