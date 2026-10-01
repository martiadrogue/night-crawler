import pytest
from night_crawler.schemas.crawler import CrawlerUpdate
from night_crawler.schemas.crawler_execution import CrawlerExecutionCreate
from night_crawler.schemas.message_aid import MessageAidCreate
from night_crawler.schemas.message_aid_rate_limit import MessageAidRateLimitCreate
from night_crawler.schemas.message_selector import MessageSelectorCreate
from night_crawler.schemas.message_template import (
    MessageTemplateCreate,
    MessageTemplateUpdate,
)
from night_crawler.services import (
    crawler_execution_service,
    crawler_service,
    crawler_version_service,
    execution_plan_service,
    message_aid_rate_limit_service,
    message_aid_service,
    message_selector_service,
    message_template_service,
)


async def _published_crawler(write_repositories, member, create_crawler, **overrides):
    crawler = await create_crawler(**overrides)
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    root_id = draft.message_template_root_id
    await message_template_service.update_template(
        write_repositories,
        member,
        root_id,
        MessageTemplateUpdate(url="https://example.com/{{place_id}}"),
    )
    search = await message_template_service.create_template(
        write_repositories,
        member,
        draft.id,
        MessageTemplateCreate(action="GET", url="https://example.com/search"),
    )
    await message_selector_service.create_selector(
        write_repositories,
        member,
        search.id,
        MessageSelectorCreate(path="//a", type="value", title="place_id"),
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    return crawler, root_id, search.id


@pytest.mark.anyio
async def test_the_plan_orders_templates_and_loads_the_seeded_context(
    write_repositories, read_repositories, member, create_crawler, execution_dispatcher
):
    crawler, root_id, search_id = await _published_crawler(
        write_repositories, member, create_crawler
    )
    execution = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"parish[]": ["Canillo"]}),
    )

    plan = await execution_plan_service.build_execution_plan(
        read_repositories, execution.id
    )

    assert [search_id, root_id] == [template.id for template in plan.ordered_templates]
    assert {"parish[]": ["Canillo"]} == plan.context
    assert "published" == plan.version.status
    assert crawler.id == plan.crawler.id


@pytest.mark.anyio
async def test_the_plan_loads_the_rate_limits_its_aids_use(
    write_repositories, read_repositories, member, create_crawler, execution_dispatcher
):
    rate_limit = await message_aid_rate_limit_service.create_rate_limit(
        write_repositories,
        MessageAidRateLimitCreate(name="example.com", rate_limit_string="5/second"),
    )
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    await message_aid_service.upsert_aid(
        write_repositories,
        member,
        draft.message_template_root_id,
        MessageAidCreate(rate_limit_id=rate_limit.id),
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    execution = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(),
    )

    plan = await execution_plan_service.build_execution_plan(
        read_repositories, execution.id
    )

    assert [rate_limit.id] == list(plan.rate_limits_by_id)
    assert "5/second" == plan.rate_limits_by_id[rate_limit.id].rate_limit_string


@pytest.mark.anyio
async def test_a_missing_execution_has_no_plan(read_repositories):
    assert None is await execution_plan_service.build_execution_plan(
        read_repositories, "missing"
    )


@pytest.mark.anyio
async def test_scheduled_crawlers_need_a_schedule_and_a_publish(
    write_repositories, read_repositories, member, create_crawler
):
    scheduled, _root, _search = await _published_crawler(
        write_repositories, member, create_crawler, title="Scheduled"
    )
    await crawler_service.update_crawler(
        write_repositories,
        member,
        scheduled.id,
        CrawlerUpdate(schedule="*/5 * * * *"),
    )
    await create_crawler(title="Never published", schedule="* * * * *")

    found = await execution_plan_service.get_scheduled_crawlers(read_repositories)

    assert [scheduled.id] == [item.crawler.id for item in found]
