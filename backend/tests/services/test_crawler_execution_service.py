import logging
from dataclasses import replace
from datetime import timedelta
from unittest.mock import create_autospec

import pytest
from night_crawler.domain.bundles.execution_plan import RunOutcome
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.model.entities import MessageSelector
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from night_crawler.domain.rules.context_entries import entries_to_context
from night_crawler.domain.rules.dataset_export_names import export_file_stem
from night_crawler.schemas.crawler import CrawlerUpdate
from night_crawler.schemas.crawler_execution import (
    CrawlerExecutionCreate,
    CrawlerExecutionHistoryQuery,
    CrawlerExecutionQuery,
    CrawlerExecutionWindowQuery,
)
from night_crawler.services import (
    crawler_execution_service,
    crawler_service,
    crawler_version_service,
)


def _metrics():
    return create_autospec(AbstractExecutionMetrics, instance=True)


async def _context_of(write_repositories, execution_id):
    entries = await write_repositories.crawler_execution_contexts.get_all_by_crawler_execution_ids(
        [execution_id]
    )
    return entries_to_context([(e.key, e.position, e.value) for e in entries])


async def _publish(write_repositories, member, crawler_id: str):
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler_id
    )
    await crawler_service.update_crawler(
        write_repositories, member, crawler_id, CrawlerUpdate(queue="priority")
    )
    return await crawler_version_service.publish_draft(
        write_repositories, member, crawler_id, draft.id
    )


@pytest.mark.anyio
async def test_create_execution_is_pending_on_the_crawler_queue(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    published = await _publish(write_repositories, member, crawler.id)

    execution = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    assert "pending" == execution.status
    assert "pending" == execution.parsing_status
    assert "priority" == execution.queue
    assert published.id == execution.crawler_version_id
    assert crawler.title == execution.crawler_title
    assert 0 == execution.metrics.request_count
    assert None is execution.started_at
    assert [(execution.id, "priority")] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_create_execution_needs_a_published_version(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()

    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.create_execution(
            write_repositories, member, execution_dispatcher, crawler.id
        )

    assert 409 == exc_info.value.status_code
    assert [] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_get_executions_lists_a_crawlers_runs(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    page = await crawler_execution_service.get_executions(
        write_repositories, member, crawler.id, CrawlerExecutionHistoryQuery()
    )
    fetched = await crawler_execution_service.get_execution(
        write_repositories, member, created.id
    )

    assert [created.id] == [execution.id for execution in page.items]
    assert (50, 0, False) == (page.limit, page.offset, page.has_more)
    assert created.id == fetched.id


@pytest.mark.anyio
async def test_get_execution_raises_when_missing(write_repositories, member):
    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.get_execution(
            write_repositories, member, "missing"
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_create_execution_seeds_its_context(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)

    execution = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(
            context={"parish[]": ["Canillo", "Encamp"], "api_key": "secret"}
        ),
    )

    assert {
        "parish[]": ["Canillo", "Encamp"],
        "api_key": "secret",
    } == await _context_of(write_repositories, execution.id)
    assert ["api_key", "parish[]"] == execution.context_keys


@pytest.mark.anyio
@pytest.mark.parametrize(
    "context",
    [
        {"_pagination": {}},
        {"parish[]": "Canillo"},
        {"": "x"},
        {"token": {"a": 1}},
        {"parish[]": [["nested"]]},
    ],
)
async def test_create_execution_rejects_an_invalid_context(
    write_repositories, member, create_crawler, execution_dispatcher, context
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)

    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.create_execution(
            write_repositories,
            member,
            execution_dispatcher,
            crawler.id,
            CrawlerExecutionCreate(context=context),
        )

    assert 400 == exc_info.value.status_code


@pytest.mark.anyio
async def test_deleting_the_crawler_removes_execution_contexts(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    execution = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"parish[]": ["Ordino"]}),
    )

    await crawler_service.delete_crawler(write_repositories, member, crawler.id)

    assert [] == await write_repositories.crawler_execution_contexts.get_all_by_crawler_execution_ids(
        [execution.id]
    )


@pytest.mark.anyio
async def test_start_execution_moves_a_pending_run_to_running_once(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    first = await crawler_execution_service.start_execution(
        write_repositories, created.id
    )
    second = await crawler_execution_service.start_execution(
        write_repositories, created.id
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    assert first
    assert not second
    assert "running" == execution.status
    assert None is not execution.started_at


@pytest.mark.anyio
async def test_finish_execution_saves_context_metrics_and_status(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    execution_metrics,
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"parish[]": ["Canillo"]}),
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)

    await crawler_execution_service.finish_execution(
        write_repositories,
        export_storage,
        execution_metrics,
        created.id,
        RunOutcome(
            context={"parish[]": ["Canillo"], "place_id[]": ["p1", "p2"]},
            request_count=3,
            error_count=1,
        ),
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    assert "succeeded" == execution.status
    assert None is not execution.finished_at
    assert 3 == execution.metrics["request_count"]
    assert 1 == execution.metrics["error_count"]
    assert {"parish[]": ["Canillo"], "place_id[]": ["p1", "p2"]} == await _context_of(
        write_repositories, created.id
    )


@pytest.mark.anyio
async def test_a_failed_outcome_marks_the_run_failed(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    execution_metrics,
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    await crawler_execution_service.finish_execution(
        write_repositories,
        export_storage,
        execution_metrics,
        created.id,
        RunOutcome(context={}, failure="Required placeholder is missing: x"),
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    assert "failed" == execution.status
    assert [(created.id, "failed")] == [
        (finished.id, finished.status) for finished in execution_metrics.finished
    ]


@pytest.mark.anyio
async def test_finish_execution_records_the_finished_run(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    execution_metrics,
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)

    await crawler_execution_service.finish_execution(
        write_repositories,
        export_storage,
        execution_metrics,
        created.id,
        RunOutcome(context={}, request_count=2, retry_count=1),
    )

    [finished] = execution_metrics.finished
    assert created.id == finished.id
    assert "succeeded" == finished.status
    assert None is not finished.started_at
    assert None is not finished.finished_at
    assert 2 == finished.metrics["request_count"]
    assert 1 == finished.metrics["retry_count"]


@pytest.mark.anyio
async def test_a_new_execution_starts_from_the_last_ones_context(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"token": "a", "parish[]": ["Ordino"]}),
    )

    second = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"token": "b"}),
    )

    assert {"token": "b", "parish[]": ["Ordino"]} == await _context_of(
        write_repositories, second.id
    )


@pytest.mark.anyio
async def test_create_test_execution_runs_the_draft_on_the_testing_queue(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )

    execution = await crawler_execution_service.create_test_execution(
        write_repositories, member, execution_dispatcher, draft.id
    )

    assert "pending" == execution.status
    assert "testing" == execution.queue
    assert draft.id == execution.crawler_version_id
    assert [(execution.id, "testing")] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_create_test_execution_runs_an_archived_version(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    first = await _publish(write_repositories, member, crawler.id)
    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )

    execution = await crawler_execution_service.create_test_execution(
        write_repositories, member, execution_dispatcher, first.id
    )

    archived = await write_repositories.crawler_versions.get_by_id(first.id)
    assert "archived" == archived.status
    assert first.id == execution.crawler_version_id


@pytest.mark.anyio
async def test_create_test_execution_raises_for_a_missing_version(
    write_repositories, member, execution_dispatcher
):
    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.create_test_execution(
            write_repositories, member, execution_dispatcher, "missing"
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_test_runs_never_become_the_context_later_runs_inherit(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    published = await _publish(write_repositories, member, crawler.id)
    await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"parish": "Encamp"}),
    )

    test_run = await crawler_execution_service.create_test_execution(
        write_repositories,
        member,
        execution_dispatcher,
        published.id,
        CrawlerExecutionCreate(context={"parish": "Canillo"}),
    )

    assert {"parish": "Canillo"} == await _context_of(write_repositories, test_run.id)
    assert {"parish": "Encamp"} == await crawler_execution_service.get_last_context(
        write_repositories, crawler.id
    )


async def _runs(write_repositories, member, create_crawler, execution_dispatcher):
    """Two Crawlers' runs: one running, two still pending, newest last."""
    runs = []
    for title in ("Venues", "Reviews"):
        crawler = await create_crawler(title=title)
        await _publish(write_repositories, member, crawler.id)
        runs.append(
            await crawler_execution_service.create_execution(
                write_repositories, member, execution_dispatcher, crawler.id
            )
        )
    runs.append(
        await crawler_execution_service.create_execution(
            write_repositories, member, execution_dispatcher, runs[1].crawler_id
        )
    )
    await crawler_execution_service.start_execution(write_repositories, runs[0].id)
    return runs


@pytest.mark.anyio
async def test_get_all_executions_lists_every_crawlers_runs_newest_first(
    write_repositories, member, create_crawler, execution_dispatcher
):
    runs = await _runs(write_repositories, member, create_crawler, execution_dispatcher)

    page = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery()
    )

    assert [run.id for run in reversed(runs)] == [item.id for item in page.items]
    assert ["Reviews", "Reviews", "Venues"] == [
        item.crawler_title for item in page.items
    ]
    assert (50, 0, False) == (page.limit, page.offset, page.has_more)


@pytest.mark.anyio
async def test_get_all_executions_paginates_when_unfiltered(
    write_repositories, member, create_crawler, execution_dispatcher
):
    runs = await _runs(write_repositories, member, create_crawler, execution_dispatcher)

    page = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(limit=1, offset=1)
    )

    assert [runs[1].id] == [item.id for item in page.items]
    assert page.has_more


@pytest.mark.anyio
async def test_get_all_executions_filters_by_status_and_parsing_status(
    write_repositories, member, create_crawler, execution_dispatcher
):
    runs = await _runs(write_repositories, member, create_crawler, execution_dispatcher)

    running = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(status="running")
    )
    pending_parsing = await crawler_execution_service.get_all_executions(
        write_repositories,
        member,
        CrawlerExecutionQuery(status="pending", parsing_status="pending", limit=1),
    )
    parsed = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(parsing_status="parsed")
    )

    assert [runs[0].id] == [item.id for item in running.items]
    assert [runs[2].id, runs[1].id] == [item.id for item in pending_parsing.items]
    assert (50, 0) == (pending_parsing.limit, pending_parsing.offset)
    assert [] == parsed.items


@pytest.mark.anyio
async def test_get_all_executions_filters_by_crawler_title_and_queue(
    write_repositories, member, create_crawler, execution_dispatcher
):
    runs = await _runs(write_repositories, member, create_crawler, execution_dispatcher)

    reviews = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(crawler_title="view")
    )
    by_queue = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(queue="priority")
    )
    nowhere = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(queue="real-time")
    )
    literal = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery(crawler_title=".*")
    )

    assert [runs[2].id, runs[1].id] == [item.id for item in reviews.items]
    assert 3 == len(by_queue.items)
    assert (50, 0) == (reviews.limit, reviews.offset)
    assert [] == nowhere.items
    assert [] == literal.items


async def _finished_run(
    write_repositories, member, create_crawler, dispatcher, storage
):
    """Run one execution to the end with a single dataset row."""
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, dispatcher, crawler.id
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)
    await crawler_execution_service.finish_execution(
        write_repositories,
        storage,
        _metrics(),
        created.id,
        RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}]),
    )
    return crawler, created


@pytest.mark.anyio
async def test_a_finished_run_exports_its_csv_and_records_the_file(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            created.id
        )
    )
    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    path = f"/exports/raw/{export_file_stem(execution)}.csv"
    assert path.startswith(f"/exports/raw/{crawler.id}_{created.id}_")
    assert path == dataset.file_path  # no rating anywhere: invalid, stays raw
    assert {path: "item_id,name,rating\r\np1,Casa,\r\n"} == export_storage.exports
    assert not hasattr(dataset, "csv_content")


@pytest.mark.anyio
async def test_a_failed_export_fails_the_run_but_keeps_its_report(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    caplog,
):
    export_storage.is_failing = True
    caplog.set_level(logging.INFO, logger="night_crawler")

    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            created.id
        )
    )
    assert ("failed", "failed") == (execution.status, execution.parsing_status)
    assert None is dataset.file_path
    assert 1 == dataset.row_count
    assert any(
        "failure=Dataset CSV export failed: Disk full." in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_a_failed_export_adds_to_the_runs_own_failure(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    caplog,
):
    export_storage.is_failing = True
    caplog.set_level(logging.INFO, logger="night_crawler")

    await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, failure="Request failed: 500"),
    )

    assert any(
        "failure=Request failed: 500; Dataset CSV export failed: Disk full."
        in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_a_run_whose_export_failed_has_no_csv_to_download(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    export_storage.is_failing = True
    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    with pytest.raises(ValidationException) as no_file:
        await crawler_execution_service.get_execution_csv(
            write_repositories, member, export_storage, created.id
        )

    assert 404 == no_file.value.status_code


@pytest.mark.anyio
async def test_get_execution_csv_returns_the_runs_csv(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    csv_file = await crawler_execution_service.get_execution_csv(
        write_repositories, member, export_storage, created.id
    )

    assert f"{created.id}.csv" == csv_file.filename
    assert csv_file.csv_content.startswith("item_id,name,rating")
    assert csv_file.csv_content in export_storage.exports.values()


@pytest.mark.anyio
async def test_the_sample_csv_of_a_small_run_is_the_whole_csv(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    sample = await crawler_execution_service.get_execution_sample_csv(
        write_repositories, member, export_storage, created.id
    )
    full = await crawler_execution_service.get_execution_csv(
        write_repositories, member, export_storage, created.id
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    started = f"{execution.started_at:%Y%m%dT%H%M%SZ}"
    assert f"{execution.crawler_id}_{created.id}_{started}-sample.csv" == (
        sample.filename
    )
    assert full.csv_content == sample.csv_content


@pytest.mark.anyio
async def test_the_sample_csv_keeps_at_most_the_sample_size(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    monkeypatch,
):
    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )
    monkeypatch.setattr(crawler_execution_service, "DATASET_SAMPLE_SIZE", 0)

    sample = await crawler_execution_service.get_execution_sample_csv(
        write_repositories, member, export_storage, created.id
    )

    assert "item_id,name,rating\r\n" == sample.csv_content


@pytest.mark.anyio
async def test_a_run_without_a_csv_has_no_sample_either(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    with pytest.raises(ValidationException) as no_csv:
        await crawler_execution_service.get_execution_sample_csv(
            write_repositories, member, export_storage, pending.id
        )

    assert 404 == no_csv.value.status_code


@pytest.mark.anyio
async def test_a_run_without_a_csv_has_nothing_to_download(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    with pytest.raises(ValidationException) as no_csv:
        await crawler_execution_service.get_execution_csv(
            write_repositories, member, export_storage, pending.id
        )
    with pytest.raises(ValidationException) as no_run:
        await crawler_execution_service.get_execution_csv(
            write_repositories, member, export_storage, "missing"
        )

    assert (404, 404) == (no_csv.value.status_code, no_run.value.status_code)


async def _finish_with(
    write_repositories, member, create_crawler, dispatcher, storage, outcome
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, dispatcher, crawler.id
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)
    await crawler_execution_service.finish_execution(
        write_repositories, storage, _metrics(), created.id, outcome
    )
    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            created.id
        )
    )
    return execution, dataset


@pytest.mark.anyio
async def test_a_valid_dataset_is_parsed_with_its_report(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(
            context={},
            dataset_rows=[{"item_id": "p1", "name": "Casa", "rating": "4.5"}],
        ),
    )

    assert ("succeeded", "parsed") == (execution.status, execution.parsing_status)
    assert dataset.validation["is_valid"]
    assert 1 == dataset.validation["rows_checked"]


@pytest.mark.anyio
async def test_validation_drops_rows_before_the_csv_and_fails_parsing(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(
            context={},
            dataset_rows=[
                {"item_id": "p1", "name": "Casa", "rating": "4.5"},
                {"item_id": "p1", "name": "Again", "rating": "4.0"},
                {"item_id": "p2", "name": "", "rating": "3.0"},
                {"item_id": "p3", "name": "Nou", "rating": "n/a"},
            ],
        ),
    )

    assert ("succeeded", "failed") == (execution.status, execution.parsing_status)
    assert "item_id,name,rating\r\np1,Casa,4.5\r\np3,Nou,n/a\r\n" == (
        export_storage.exports[dataset.file_path]
    )
    assert 2 == dataset.row_count
    assert {
        "rows_checked": 4,
        "rows_dropped_missing_required": 1,
        "rows_dropped_duplicate": 1,
        "type_mismatches": {"rating": 1},
        "pattern_mismatches": {},
        "empty_columns": [],
        "is_valid": False,
        "completeness_rate": 1.0,
    } == dataset.validation


@pytest.mark.anyio
async def test_a_field_empty_in_every_row_fails_parsing(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}]),
    )

    assert "failed" == execution.parsing_status
    assert ["rating"] == dataset.validation["empty_columns"]


@pytest.mark.anyio
async def test_a_failed_run_never_parses_even_with_valid_rows(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, _dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(
            context={},
            failure="Request failed: 500",
            dataset_rows=[{"item_id": "p1", "name": "Casa", "rating": "4.5"}],
        ),
    )

    assert ("failed", "failed") == (execution.status, execution.parsing_status)


@pytest.mark.anyio
async def test_runs_carry_their_validation_report(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, _dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}]),
    )
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, execution.crawler_id
    )

    finished = await crawler_execution_service.get_execution(
        write_repositories, member, execution.id
    )
    page = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery()
    )

    assert ["rating"] == finished.validation.empty_columns
    assert not finished.validation.is_valid
    assert {execution.id: ["rating"], pending.id: None} == {
        item.id: (item.validation.empty_columns if item.validation else None)
        for item in page.items
    }


VALID_ROWS = [{"item_id": "p1", "name": "Casa", "rating": "4.5"}]


@pytest.mark.anyio
async def test_a_parsed_runs_csv_moves_to_validated(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, dataset_rows=VALID_ROWS),
    )

    path = f"/exports/validated/{export_file_stem(execution)}.csv"
    assert "parsed" == execution.parsing_status
    assert path == dataset.file_path
    assert [path] == list(export_storage.exports)


@pytest.mark.anyio
async def test_a_failed_runs_valid_csv_stays_raw(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, failure="Request failed: 500", dataset_rows=VALID_ROWS),
    )

    assert f"/exports/raw/{export_file_stem(execution)}.csv" == dataset.file_path


@pytest.mark.anyio
async def test_a_failed_move_keeps_the_raw_csv_and_the_parsed_run(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    export_storage.is_move_failing = True

    execution, dataset = await _finish_with(
        write_repositories,
        member,
        create_crawler,
        execution_dispatcher,
        export_storage,
        RunOutcome(context={}, dataset_rows=VALID_ROWS),
    )

    assert "parsed" == execution.parsing_status
    assert f"/exports/raw/{export_file_stem(execution)}.csv" == dataset.file_path


async def _ended_run(
    write_repositories, member, dispatcher, storage, crawler_id, outcome
):
    """Run one execution of the Crawler's published version to the end."""
    created = await crawler_execution_service.create_execution(
        write_repositories, member, dispatcher, crawler_id
    )
    await crawler_execution_service.start_execution(write_repositories, created.id)
    await crawler_execution_service.finish_execution(
        write_repositories, storage, _metrics(), created.id, outcome
    )
    return await write_repositories.crawler_executions.get_by_id(created.id)


SUCCESS = RunOutcome(context={}, dataset_rows=VALID_ROWS)
FAILURE = RunOutcome(context={}, failure="Request failed: 500")
UNPARSED = RunOutcome(context={}, dataset_rows=[{"item_id": "p1", "name": "Casa"}])


async def _history(write_repositories, member, create_crawler, dispatcher, storage):
    """A Crawler's runs, oldest first, and a failed test run of its draft."""
    crawler = await create_crawler()
    published = await _publish(write_repositories, member, crawler.id)
    runs = [
        await _ended_run(
            write_repositories, member, dispatcher, storage, crawler.id, outcome
        )
        for outcome in (SUCCESS, FAILURE, UNPARSED, SUCCESS, SUCCESS)
    ]
    test_run = await crawler_execution_service.create_test_execution(
        write_repositories, member, dispatcher, published.id
    )
    await crawler_execution_service.start_execution(write_repositories, test_run.id)
    await crawler_execution_service.finish_execution(
        write_repositories, storage, _metrics(), test_run.id, FAILURE
    )
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, dispatcher, crawler.id
    )
    return crawler, runs, test_run, pending


@pytest.mark.anyio
async def test_get_executions_pages_a_crawlers_runs_without_test_runs(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, runs, test_run, pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    first = await crawler_execution_service.get_executions(
        write_repositories, member, crawler.id, CrawlerExecutionHistoryQuery(limit=2)
    )
    second = await crawler_execution_service.get_executions(
        write_repositories,
        member,
        crawler.id,
        CrawlerExecutionHistoryQuery(limit=2, offset=2),
    )
    failed = await crawler_execution_service.get_executions(
        write_repositories,
        member,
        crawler.id,
        CrawlerExecutionHistoryQuery(status="failed"),
    )
    tests = await crawler_execution_service.get_executions(
        write_repositories,
        member,
        crawler.id,
        CrawlerExecutionHistoryQuery(queue="testing"),
    )

    assert [pending.id, runs[4].id] == [item.id for item in first.items]
    assert first.has_more
    assert [runs[3].id, runs[2].id] == [item.id for item in second.items]
    assert [runs[1].id] == [item.id for item in failed.items]
    assert [test_run.id] == [item.id for item in tests.items]


@pytest.mark.anyio
async def test_get_executions_raises_for_a_missing_crawler(write_repositories, member):
    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.get_executions(
            write_repositories, member, "missing", CrawlerExecutionHistoryQuery()
        )

    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_runs_carry_their_dataset_counts(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    finished = await _ended_run(
        write_repositories,
        member,
        execution_dispatcher,
        export_storage,
        crawler.id,
        SUCCESS,
    )
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    page = await crawler_execution_service.get_all_executions(
        write_repositories, member, CrawlerExecutionQuery()
    )
    fetched = await crawler_execution_service.get_execution(
        write_repositories, member, finished.id
    )

    datasets = {item.id: item.dataset for item in page.items}
    assert None is datasets[pending.id]
    assert 1 == datasets[finished.id].row_count
    assert 0 == datasets[finished.id].import_metrics.records_inserted
    assert 1 == fetched.dataset.row_count
    assert fetched.validation.is_valid


@pytest.mark.anyio
async def test_the_execution_summary_covers_the_crawlers_ended_runs(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, runs, _test_run, _pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    summary = await crawler_execution_service.get_execution_summary(
        write_repositories, member, crawler.id
    )

    assert 2 == summary.consecutive_successful_runs
    assert 0.6 == summary.success_rate
    assert 5 == summary.recent_run_count
    assert runs[4].finished_at == summary.last_success_at
    assert 0 <= summary.avg_completion_seconds


@pytest.mark.anyio
async def test_the_execution_summary_of_test_runs_only(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, _runs, _test_run, _pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    summary = await crawler_execution_service.get_execution_summary(
        write_repositories, member, crawler.id, queue="testing"
    )

    assert (0, 0.0, 1) == (
        summary.consecutive_successful_runs,
        summary.success_rate,
        summary.recent_run_count,
    )
    assert None is summary.last_success_at
    assert None is summary.avg_completion_seconds


@pytest.mark.anyio
async def test_the_streak_keeps_counting_past_the_summary_window(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    monkeypatch,
):
    monkeypatch.setattr(crawler_execution_service, "SUMMARY_WINDOW", 2)
    monkeypatch.setattr(crawler_execution_service, "STREAK_SCAN_SIZE", 2)
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    for outcome in (FAILURE, SUCCESS, SUCCESS, SUCCESS, SUCCESS, SUCCESS):
        await _ended_run(
            write_repositories,
            member,
            execution_dispatcher,
            export_storage,
            crawler.id,
            outcome,
        )

    summary = await crawler_execution_service.get_execution_summary(
        write_repositories, member, crawler.id
    )

    assert 5 == summary.consecutive_successful_runs
    assert (1.0, 2) == (summary.success_rate, summary.recent_run_count)


@pytest.mark.anyio
async def test_the_execution_summary_of_a_crawler_without_runs(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    summary = await crawler_execution_service.get_execution_summary(
        write_repositories, member, crawler.id
    )
    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.get_execution_summary(
            write_repositories, member, "missing"
        )

    assert (0, None, 0) == (
        summary.consecutive_successful_runs,
        summary.success_rate,
        summary.recent_run_count,
    )
    assert None is summary.avg_completion_seconds
    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_runs_carry_their_outcome_and_completeness(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    unparsed = await _ended_run(
        write_repositories,
        member,
        execution_dispatcher,
        export_storage,
        crawler.id,
        UNPARSED,
    )
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    fetched = await crawler_execution_service.get_execution(
        write_repositories, member, unparsed.id
    )
    page = await crawler_execution_service.get_executions(
        write_repositories, member, crawler.id, CrawlerExecutionHistoryQuery()
    )

    assert "verification_failed" == fetched.outcome
    assert 2 / 3 == fetched.validation.completeness_rate
    assert {pending.id: "in_progress", unparsed.id: "verification_failed"} == {
        item.id: item.outcome for item in page.items
    }


@pytest.mark.anyio
async def test_a_report_saved_before_completeness_existed_reads_as_none(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    finished = await _ended_run(
        write_repositories,
        member,
        execution_dispatcher,
        export_storage,
        crawler.id,
        SUCCESS,
    )
    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            finished.id
        )
    )
    old_report = {
        key: value
        for key, value in dataset.validation.items()
        if "completeness_rate" != key
    }
    await write_repositories.crawler_execution_datasets.save(
        replace(dataset, validation=old_report)
    )

    fetched = await crawler_execution_service.get_execution(
        write_repositories, member, finished.id
    )

    assert "success" == fetched.outcome
    assert None is fetched.validation.completeness_rate
    assert fetched.validation.is_valid


async def _move_back(write_repositories, execution, days):
    """Pretend a run was created `days` days earlier."""
    await write_repositories.crawler_executions.save(
        replace(execution, created_at=execution.created_at - timedelta(days=days))
    )


@pytest.mark.anyio
async def test_execution_history_covers_the_window_without_test_runs(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, runs, test_run, pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )
    await _move_back(write_repositories, runs[0], days=31)

    history = await crawler_execution_service.get_execution_history(
        write_repositories, member, crawler.id, CrawlerExecutionWindowQuery()
    )
    tests = await crawler_execution_service.get_execution_history(
        write_repositories,
        member,
        crawler.id,
        CrawlerExecutionWindowQuery(queue="testing"),
    )

    assert [pending.id, runs[4].id, runs[3].id, runs[2].id, runs[1].id] == [
        run.id for run in history.runs
    ]
    assert {
        "all": 5,
        "success": 2,
        "verification_failed": 1,
        "failed": 1,
        "in_progress": 1,
    } == history.counts.model_dump()
    assert not history.is_truncated
    assert timedelta(days=30) == history.window_end - history.window_start
    assert [test_run.id] == [run.id for run in tests.runs]
    assert (1, 1) == (tests.counts.all, tests.counts.failed)


@pytest.mark.anyio
async def test_execution_history_follows_the_days_asked(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, runs, _test_run, _pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )
    await _move_back(write_repositories, runs[0], days=31)

    longer = await crawler_execution_service.get_execution_history(
        write_repositories, member, crawler.id, CrawlerExecutionWindowQuery(days=90)
    )

    assert runs[0].id == longer.runs[-1].id
    assert 6 == longer.counts.all


@pytest.mark.anyio
async def test_execution_history_caps_its_runs_but_counts_them_all(
    write_repositories,
    member,
    create_crawler,
    execution_dispatcher,
    export_storage,
    monkeypatch,
):
    crawler, runs, _test_run, pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )
    monkeypatch.setattr(crawler_execution_service, "HISTORY_WINDOW_MAX_RUNS", 2)

    history = await crawler_execution_service.get_execution_history(
        write_repositories, member, crawler.id, CrawlerExecutionWindowQuery()
    )

    assert [pending.id, runs[4].id] == [run.id for run in history.runs]
    assert history.is_truncated
    assert 6 == history.counts.all


@pytest.mark.anyio
async def test_execution_history_of_a_crawler_without_runs(
    write_repositories, member, create_crawler
):
    crawler = await create_crawler()

    history = await crawler_execution_service.get_execution_history(
        write_repositories, member, crawler.id, CrawlerExecutionWindowQuery()
    )
    with pytest.raises(ValidationException) as exc_info:
        await crawler_execution_service.get_execution_history(
            write_repositories, member, "missing", CrawlerExecutionWindowQuery()
        )

    assert [] == history.runs
    assert 0 == history.counts.all
    assert not history.is_truncated
    assert 404 == exc_info.value.status_code


@pytest.mark.anyio
async def test_the_summary_dates_the_last_failures_and_averages_completeness(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler, runs, _test_run, _pending = await _history(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    summary = await crawler_execution_service.get_execution_summary(
        write_repositories, member, crawler.id
    )
    empty = await crawler_execution_service.get_execution_summary(
        write_repositories, member, (await create_crawler()).id
    )

    assert runs[2].finished_at == summary.last_verification_failure_at
    assert runs[1].finished_at == summary.last_failure_at
    assert 1.0 == summary.avg_completeness_rate
    assert (None, None, None) == (
        empty.last_verification_failure_at,
        empty.last_failure_at,
        empty.avg_completeness_rate,
    )


async def _publish_with_selectors(write_repositories, member, crawler_id, titles):
    """Publish the draft with a value selector per title on its root."""
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler_id
    )
    for title in titles:
        await write_repositories.message_selectors.save(
            MessageSelector(
                id=f"selector-{title}",
                message_template_id=draft.message_template_root_id,
                parent_selector_id=None,
                path="//x",
                type="value",
                target="__text",
                created_at=draft.created_at,
                updated_at=draft.created_at,
                title=title,
            )
        )
    return await crawler_version_service.publish_draft(
        write_repositories, member, crawler_id, draft.id
    )


@pytest.mark.anyio
async def test_a_new_run_never_inherits_harvested_values(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish_with_selectors(
        write_repositories, member, crawler.id, ["place_id", "token"]
    )
    first = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    await crawler_execution_service.save_context(
        write_repositories,
        first.id,
        {"place_id[]": ["p1", "p2"], "token": "t1", "api_key": "secret"},
    )

    second = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    seeded = await crawler_execution_service.create_execution(
        write_repositories,
        member,
        execution_dispatcher,
        crawler.id,
        CrawlerExecutionCreate(context={"place_id[]": ["p9"]}),
    )

    assert {"api_key": "secret"} == await _context_of(write_repositories, second.id)
    assert {"api_key": "secret", "place_id[]": ["p9"]} == await _context_of(
        write_repositories, seeded.id
    )
    assert {
        "place_id[]": ["p1", "p2"],
        "token": "t1",
        "api_key": "secret",
    } == await _context_of(write_repositories, first.id)


@pytest.mark.anyio
async def test_a_test_run_drops_the_keys_its_own_version_harvests(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish_with_selectors(write_repositories, member, crawler.id, ["token"])
    first = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )
    await crawler_execution_service.save_context(
        write_repositories, first.id, {"token": "t1", "page": 2}
    )
    draft = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    await write_repositories.message_selectors.save(
        MessageSelector(
            id="selector-page",
            message_template_id=draft.message_template_root_id,
            parent_selector_id=None,
            path="//x",
            type="value",
            target="__text",
            created_at=draft.created_at,
            updated_at=draft.created_at,
            title="page",
        )
    )

    test_run = await crawler_execution_service.create_test_execution(
        write_repositories, member, execution_dispatcher, draft.id
    )

    assert {} == await _context_of(write_repositories, test_run.id)
