from dataclasses import replace
from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import (
    CrawlerExecution,
    MessageAid,
    MessageSelector,
)
from night_crawler.schemas.crawler_version import CrawlerVersionUpdate
from night_crawler.services import crawler_version_service

NOW = datetime(2026, 1, 1)


async def _published_crawler(write_repositories, member, create_crawler):
    """Create a crawler and publish its first draft."""
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    published = await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    return crawler, published


@pytest.mark.anyio
async def test_create_draft_refuses_a_second_draft(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.create_draft(
            write_repositories, member, crawler.id
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_publish_draft_archives_the_previous_version(
    write_repositories, member, create_crawler
):
    crawler, first = await _published_crawler(
        write_repositories, member, create_crawler
    )
    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )

    second = await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )

    assert "published" == second.status
    assert first.id != second.id
    archived = await write_repositories.crawler_versions.get_by_id(first.id)
    assert "archived" == archived.status


@pytest.mark.anyio
async def test_publish_refuses_a_version_that_is_not_a_draft(
    write_repositories, member, create_crawler
):
    crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.publish_draft(
            write_repositories, member, crawler.id, published.id
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_draft_clones_the_published_tree(
    write_repositories, member, create_crawler
):
    crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )
    root_id = published.message_template_root_id
    for selector_id, parent_id in (("parent", None), ("child", "parent")):
        await write_repositories.message_selectors.save(
            MessageSelector(
                id=selector_id,
                message_template_id=root_id,
                parent_selector_id=parent_id,
                path="//div",
                type="value",
                target="__text",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await write_repositories.message_aids.save(
        MessageAid(
            id="aid-1",
            message_template_id=root_id,
            render_mode="playwright",
            created_at=NOW,
            updated_at=NOW,
        )
    )

    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )

    assert root_id != draft.message_template_root_id
    cloned = await write_repositories.message_selectors.get_all_by_message_template_id(
        draft.message_template_root_id
    )
    cloned_by_parent = {selector.parent_selector_id: selector for selector in cloned}
    cloned_parent = cloned_by_parent[None]
    assert cloned_parent.id == next(
        selector.parent_selector_id
        for selector in cloned
        if selector.parent_selector_id
    )
    aid = await write_repositories.message_aids.get_by_message_template_id(
        draft.message_template_root_id
    )
    assert "playwright" == aid.render_mode


@pytest.mark.anyio
async def test_editing_a_published_version_auto_forks_a_draft(
    write_repositories, member, create_crawler
):
    _crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )

    edited = await crawler_version_service.update_version(
        write_repositories,
        member,
        published.id,
        CrawlerVersionUpdate(is_host_session_sharing_enabled=False),
    )

    assert "draft" == edited.status
    assert False is edited.is_host_session_sharing_enabled
    assert "queue" not in edited.model_dump()
    unchanged = await write_repositories.crawler_versions.get_by_id(published.id)
    assert True is unchanged.is_host_session_sharing_enabled


@pytest.mark.anyio
async def test_editing_an_archived_version_is_refused(
    write_repositories, member, create_crawler
):
    crawler, first = await _published_crawler(
        write_repositories, member, create_crawler
    )
    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.update_version(
            write_repositories,
            member,
            first.id,
            CrawlerVersionUpdate(is_host_session_sharing_enabled=False),
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_set_root_template_rejects_a_template_of_another_version(
    write_repositories, member, create_crawler
):
    crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )
    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.set_version_root_template(
            write_repositories, member, draft.id, published.message_template_root_id
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_version_removes_a_draft_and_its_templates(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )

    await crawler_version_service.delete_version(write_repositories, member, draft.id)

    assert None is await write_repositories.crawler_versions.get_by_id(draft.id)
    assert None is await write_repositories.message_templates.get_by_id(
        draft.message_template_root_id
    )


@pytest.mark.anyio
async def test_delete_version_refuses_the_published_version(
    write_repositories, member, create_crawler
):
    _crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.delete_version(
            write_repositories, member, published.id
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_delete_version_refuses_a_version_that_has_run(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    await write_repositories.crawler_executions.save(
        CrawlerExecution(
            id="execution-1",
            crawler_id=crawler.id,
            crawler_version_id=draft.id,
            status="succeeded",
            parsing_status="parsed",
            queue="testing",
            started_at=NOW,
            finished_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )

    with pytest.raises(ValidationException) as exc_info:
        await crawler_version_service.delete_version(
            write_repositories, member, draft.id
        )

    assert 409 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_draft_without_a_published_one_clones_the_latest_archived(
    write_repositories, member, create_crawler
):
    crawler, published = await _published_crawler(
        write_repositories, member, create_crawler
    )
    await write_repositories.message_aids.save(
        MessageAid(
            id="aid-1",
            message_template_id=published.message_template_root_id,
            render_mode="stealth",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    # Publishing is the only way to archive, so a crawler with nothing
    # published only exists in older data: write that state directly.
    await write_repositories.crawler_versions.save(
        replace(
            await write_repositories.crawler_versions.get_by_id(published.id),
            status="archived",
        )
    )

    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )

    aid = await write_repositories.message_aids.get_by_message_template_id(
        draft.message_template_root_id
    )
    assert "stealth" == aid.render_mode


@pytest.mark.anyio
async def test_create_draft_without_versions_starts_empty(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()
    [first] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    await crawler_version_service.delete_version(write_repositories, member, first.id)

    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )

    templates = (
        await write_repositories.message_templates.get_all_by_crawler_version_id(
            draft.id
        )
    )
    assert [draft.message_template_root_id] == [template.id for template in templates]
