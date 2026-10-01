from datetime import datetime
from unittest.mock import create_autospec

import pytest
from night_crawler.domain.bundles.execution_infrastructure import (
    ExecutionInfrastructure,
)
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.model.value_objects import Harvest, SessionState
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.domain.ports.request_executor import (
    AbstractRequestExecutor,
    DispatchRequest,
    DispatchResult,
)
from night_crawler.schemas.crawler import CrawlerUpdate
from night_crawler.schemas.message_selector import MessageSelectorCreate
from night_crawler.schemas.message_template import MessageTemplateUpdate
from night_crawler.services import (
    crawler_execution_service,
    crawler_service,
    crawler_version_service,
    execution_processing_service,
    message_selector_service,
    message_template_service,
)


def _rate_limiter():
    return create_autospec(AbstractRateLimiter, instance=True)


def _infrastructure(repository_factories, export_storage, executor):
    return ExecutionInfrastructure(
        repository_factories=repository_factories,
        executors=RequestExecutors(
            httpx=executor, playwright=executor, stealth=executor
        ),
        rate_limiter=_rate_limiter(),
        export_storage=export_storage,
    )


class _CrashingExecutor(AbstractRequestExecutor):
    async def execute(self, request: DispatchRequest) -> DispatchResult:
        raise RuntimeError("boom")

    async def aclose(self) -> None:
        pass


class _HarvestingExecutor(AbstractRequestExecutor):
    async def execute(self, request: DispatchRequest) -> DispatchResult:
        return DispatchResult(
            harvest=Harvest(
                rows=[
                    {"token": "abc", "name": "Casa", "item_id": "p1", "rating": "4.5"}
                ],
                array_titles=frozenset(),
            ),
            status_code=200,
            session=SessionState(),
        )

    async def aclose(self) -> None:
        pass


async def _published_crawler(write_repositories, member, create_crawler):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    await message_template_service.update_template(
        write_repositories,
        member,
        draft.message_template_root_id,
        MessageTemplateUpdate(url="https://example.com"),
    )
    for title in ("token", "name", "rating"):
        await message_selector_service.create_selector(
            write_repositories,
            member,
            draft.message_template_root_id,
            MessageSelectorCreate(path="//a", type="value", title=title),
        )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    return crawler


@pytest.mark.anyio
async def test_due_crawlers_get_a_pending_execution_on_their_queue(
    write_repositories,
    member,
    create_crawler,
    repository_factories,
    execution_dispatcher,
):
    crawler = await _published_crawler(write_repositories, member, create_crawler)
    await crawler_service.update_crawler(
        write_repositories,
        member,
        crawler.id,
        CrawlerUpdate(schedule="30 6 * * *"),
    )

    not_due = await execution_processing_service.dispatch_scheduled_crawlers(
        repository_factories, execution_dispatcher, datetime(2026, 1, 1, 6, 29)
    )
    due = await execution_processing_service.dispatch_scheduled_crawlers(
        repository_factories, execution_dispatcher, datetime(2026, 1, 1, 6, 30)
    )

    [execution] = await write_repositories.crawler_executions.get_all_by_crawler_id(
        crawler.id
    )
    assert 0 == not_due
    assert 1 == due
    assert "pending" == execution.status
    assert [(execution.id, "discovery")] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_processing_runs_the_plan_and_records_the_outcome(
    write_repositories,
    member,
    create_crawler,
    repository_factories,
    execution_dispatcher,
    export_storage,
):
    crawler = await _published_crawler(write_repositories, member, create_crawler)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    status = await execution_processing_service.process_execution(
        _infrastructure(repository_factories, export_storage, _HarvestingExecutor()),
        created.id,
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    [context] = (
        await write_repositories.crawler_execution_contexts.get_all_by_crawler_execution_ids(
            [created.id]
        )
    )
    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            created.id
        )
    )
    assert "succeeded" == status == execution.status
    assert "parsed" == execution.parsing_status
    assert 1 == execution.metrics["request_count"]
    assert ("token", "abc") == (context.key, context.value)
    assert 1 == dataset.row_count
    assert "item_id,name,rating\r\np1,Casa,4.5\r\n" == dataset.csv_content
    assert dataset.validation["is_valid"]


@pytest.mark.anyio
async def test_a_run_that_already_started_is_skipped(
    write_repositories,
    member,
    create_crawler,
    repository_factories,
    execution_dispatcher,
    export_storage,
):
    crawler = await _published_crawler(write_repositories, member, create_crawler)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)
    status = await execution_processing_service.process_execution(
        _infrastructure(repository_factories, export_storage, _HarvestingExecutor()),
        created.id,
    )

    assert "skipped" == status


@pytest.mark.anyio
async def test_a_crashed_run_is_recorded_as_failed_and_reraised(
    write_repositories,
    member,
    create_crawler,
    repository_factories,
    execution_dispatcher,
    export_storage,
):
    crawler = await _published_crawler(write_repositories, member, create_crawler)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    with pytest.raises(RuntimeError):
        await execution_processing_service.process_execution(
            _infrastructure(repository_factories, export_storage, _CrashingExecutor()),
            created.id,
        )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    assert "failed" == execution.status
