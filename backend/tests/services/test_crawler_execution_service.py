import pytest
from night_crawler.domain.bundles.execution_plan import RunOutcome
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.rules.context_entries import entries_to_context
from night_crawler.domain.rules.dataset_export_names import export_file_stem
from night_crawler.schemas.crawler import CrawlerUpdate
from night_crawler.schemas.crawler_execution import (
    CrawlerExecutionCreate,
    CrawlerExecutionQuery,
)
from night_crawler.services import (
    crawler_execution_service,
    crawler_service,
    crawler_version_service,
)


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

    executions = await crawler_execution_service.get_executions(
        write_repositories, member, crawler.id
    )
    fetched = await crawler_execution_service.get_execution(
        write_repositories, member, created.id
    )

    assert [created.id] == [execution.id for execution in executions]
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
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
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
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    created = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    await crawler_execution_service.finish_execution(
        write_repositories,
        export_storage,
        created.id,
        RunOutcome(context={}, failure="Required placeholder is missing: x"),
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    assert "failed" == execution.status


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
    assert {path: dataset.csv_content} == export_storage.exports
    assert "item_id,name,rating\r\np1,Casa,\r\n" == dataset.csv_content


@pytest.mark.anyio
async def test_a_failed_export_keeps_the_run_and_its_csv(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    export_storage.is_failing = True

    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    execution = await write_repositories.crawler_executions.get_by_id(created.id)
    dataset = (
        await write_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            created.id
        )
    )
    assert "succeeded" == execution.status
    assert None is dataset.file_path
    assert 1 == dataset.row_count


@pytest.mark.anyio
async def test_get_execution_csv_returns_the_runs_csv(
    write_repositories, member, create_crawler, execution_dispatcher, export_storage
):
    _crawler, created = await _finished_run(
        write_repositories, member, create_crawler, execution_dispatcher, export_storage
    )

    csv_file = await crawler_execution_service.get_execution_csv(
        write_repositories, member, created.id
    )

    assert f"{created.id}.csv" == csv_file.filename
    assert csv_file.csv_content.startswith("item_id,name,rating")


@pytest.mark.anyio
async def test_a_run_without_a_csv_has_nothing_to_download(
    write_repositories, member, create_crawler, execution_dispatcher
):
    crawler = await create_crawler()
    await _publish(write_repositories, member, crawler.id)
    pending = await crawler_execution_service.create_execution(
        write_repositories, member, execution_dispatcher, crawler.id
    )

    with pytest.raises(ValidationException) as no_csv:
        await crawler_execution_service.get_execution_csv(
            write_repositories, member, pending.id
        )
    with pytest.raises(ValidationException) as no_run:
        await crawler_execution_service.get_execution_csv(
            write_repositories, member, "missing"
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
        write_repositories, storage, created.id, outcome
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
    assert "item_id,name,rating\r\np1,Casa,4.5\r\np3,Nou,n/a\r\n" == dataset.csv_content
    assert 2 == dataset.row_count
    assert {
        "rows_checked": 4,
        "rows_dropped_missing_required": 1,
        "rows_dropped_duplicate": 1,
        "type_mismatches": {"rating": 1},
        "pattern_mismatches": {},
        "empty_columns": [],
        "is_valid": False,
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
