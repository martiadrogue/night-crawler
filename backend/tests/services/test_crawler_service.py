from datetime import datetime

import pytest
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import (
    CrawlerExecution,
    MessageAid,
    MessageSelector,
)
from night_crawler.schemas.crawler import CrawlerUpdate
from night_crawler.services import crawler_service

NOW = datetime(2026, 1, 1)


@pytest.mark.anyio
async def test_create_crawler_opens_a_first_draft_with_a_root(
    write_repositories, member, create_crawler, dataset_ids
):
    crawler = await create_crawler()

    assert member.id == crawler.user_id
    assert dataset_ids["venues"] == crawler.dataset_id
    [version] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    assert "draft" == version.status
    root = await write_repositories.message_templates.get_by_id(
        version.message_template_root_id
    )
    assert version.id == root.crawler_version_id


@pytest.mark.anyio
async def test_create_crawler_rejects_fields_outside_the_dataset(create_crawler):
    with pytest.raises(ValidationException) as exc_info:
        await create_crawler(dataset="reviews")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_crawler_accepts_a_schedule_before_anything_is_published(
    create_crawler,
):
    crawler = await create_crawler(schedule="0 * * * *")

    assert "0 * * * *" == crawler.schedule
    assert "is_active" not in crawler.model_dump()


@pytest.mark.anyio
async def test_the_queue_belongs_to_the_crawler(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    updated = await crawler_service.update_crawler(
        write_repositories, member, crawler.id, CrawlerUpdate(queue="priority")
    )

    assert "discovery" == crawler.queue
    assert "priority" == updated.queue


@pytest.mark.anyio
async def test_update_crawler_revalidates_the_fields_against_a_new_dataset(
    write_repositories, member, create_crawler, dataset_ids
):
    crawler = await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await crawler_service.update_crawler(
            write_repositories,
            member,
            crawler.id,
            CrawlerUpdate(dataset_id=dataset_ids["menus"]),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_update_crawler_applies_a_partial_update(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    updated = await crawler_service.update_crawler(
        write_repositories, member, crawler.id, CrawlerUpdate(title="Renamed")
    )

    assert "Renamed" == updated.title
    assert crawler.fields == updated.fields


@pytest.mark.anyio
async def test_delete_crawler_removes_everything_it_owns(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()
    [version] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    root_id = version.message_template_root_id
    await write_repositories.message_selectors.save(
        MessageSelector(
            id="selector-1",
            message_template_id=root_id,
            parent_selector_id=None,
            path="//h1",
            type="value",
            target="__text",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await write_repositories.message_aids.save(
        MessageAid(
            id="aid-1", message_template_id=root_id, created_at=NOW, updated_at=NOW
        )
    )
    await write_repositories.crawler_executions.save(
        CrawlerExecution(
            id="execution-1",
            crawler_id=crawler.id,
            crawler_version_id=version.id,
            status="pending",
            parsing_status="pending",
            queue="discovery",
            started_at=None,
            finished_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )

    await crawler_service.delete_crawler(write_repositories, member, crawler.id)

    assert None is await write_repositories.crawlers.get_by_id(crawler.id)
    assert [] == await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    assert None is await write_repositories.message_templates.get_by_id(root_id)
    assert None is await write_repositories.message_selectors.get_by_id("selector-1")
    assert None is await write_repositories.message_aids.get_by_message_template_id(
        root_id
    )
    assert None is await write_repositories.crawler_executions.get_by_id("execution-1")


@pytest.mark.anyio
async def test_get_crawler_raises_when_missing(write_repositories, member):
    with pytest.raises(ValidationException) as exc_info:
        await crawler_service.get_crawler_out(write_repositories, member, "missing")

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_crawler_refuses_an_unknown_source(create_crawler):
    with pytest.raises(ValidationException) as exc_info:
        await create_crawler(source_id="missing")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_crawler_refuses_an_unknown_dataset(create_crawler):
    with pytest.raises(ValidationException) as exc_info:
        await create_crawler(dataset_id="missing")

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_the_crawler_decides_which_fields_it_downloads(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    updated = await crawler_service.update_crawler(
        write_repositories,
        member,
        crawler.id,
        CrawlerUpdate(fields=["item_id", "name", "address"]),
    )

    assert ["item_id", "name", "rating"] == crawler.fields
    assert ["item_id", "name", "address"] == updated.fields


@pytest.mark.anyio
async def test_an_update_may_not_drop_a_required_field(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await crawler_service.update_crawler(
            write_repositories, member, crawler.id, CrawlerUpdate(fields=["item_id"])
        )

    assert 400 == exc_info.value.status_code
    assert "Required field 'name' is missing." in exc_info.value.message
