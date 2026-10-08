"""Use cases for Crawler Executions: creating and inspecting runs."""

import logging
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from night_crawler.domain.bundles.execution_plan import RunOutcome, ScheduledCrawler
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.model.constants import DATASET_SAMPLE_SIZE, TESTING_QUEUE
from night_crawler.domain.model.entities import (
    CrawlerExecution,
    CrawlerExecutionContext,
    CrawlerExecutionDataset,
    CrawlerVersion,
)
from night_crawler.domain.model.value_objects import DatasetValidation
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from night_crawler.domain.ports.repositories import ExecutionDatasetSummary
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.context_entries import (
    context_to_entries,
    entries_to_context,
)
from night_crawler.domain.rules.context_inheritance import (
    drop_harvested,
    harvested_keys,
)
from night_crawler.domain.rules.dataset_export_names import export_file_stem
from night_crawler.domain.rules.dataset_rows import build_csv
from night_crawler.domain.rules.dataset_sample import sample_csv
from night_crawler.domain.rules.dataset_validation import validate_dataset_rows
from night_crawler.domain.rules.execution_context import validate_seed_context
from night_crawler.domain.rules.execution_history import (
    HISTORY_WINDOW_MAX_RUNS,
    STREAK_SCAN_SIZE,
    SUMMARY_WINDOW,
    calculate_average_completeness,
    calculate_average_completion_seconds,
    calculate_success_rate,
    count_leading_successes,
    count_outcomes,
    resolve_history_queues,
    resolve_run_outcome,
)
from night_crawler.domain.rules.pagination import resolve_page
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_execution import (
    CrawlerExecutionCreate,
    CrawlerExecutionCsvOut,
    CrawlerExecutionDatasetOut,
    CrawlerExecutionHistoryOut,
    CrawlerExecutionHistoryQuery,
    CrawlerExecutionImportMetricsOut,
    CrawlerExecutionMetricsOut,
    CrawlerExecutionOut,
    CrawlerExecutionOutcomeCountsOut,
    CrawlerExecutionQuery,
    CrawlerExecutionsPageOut,
    CrawlerExecutionSummaryOut,
    CrawlerExecutionValidationOut,
    CrawlerExecutionWindowQuery,
)
from night_crawler.services import crawler_service

logger = logging.getLogger(__name__)


def _to_out(
    execution: CrawlerExecution,
    crawler_title: str,
    context_keys: list[str],
    *,
    dataset: ExecutionDatasetSummary | None = None,
) -> CrawlerExecutionOut:
    """Map an execution onto its API schema.

    Context values stay out: a seeded value may be a secret.
    `dataset` is what its CSV holds, once it finished.
    """
    return CrawlerExecutionOut(
        id=execution.id,
        crawler_id=execution.crawler_id,
        crawler_title=crawler_title,
        crawler_version_id=execution.crawler_version_id,
        status=execution.status,
        parsing_status=execution.parsing_status,
        outcome=resolve_run_outcome(execution),
        queue=execution.queue,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        resume_count=execution.resume_count,
        metrics=CrawlerExecutionMetricsOut(**execution.metrics),
        context_keys=sorted(context_keys),
        validation=_validation_out(dataset),
        dataset=_dataset_out(dataset),
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )


def _validation_out(
    dataset: ExecutionDatasetSummary | None,
) -> CrawlerExecutionValidationOut | None:
    """Return the dataset's validation report, once there is one."""
    if None is dataset or None is dataset.validation:
        return None
    return CrawlerExecutionValidationOut.model_validate(dataset.validation)


def _dataset_out(
    dataset: ExecutionDatasetSummary | None,
) -> CrawlerExecutionDatasetOut | None:
    """Return the dataset's row count and import counters, if any."""
    if None is dataset:
        return None
    return CrawlerExecutionDatasetOut(
        row_count=dataset.row_count,
        import_metrics=CrawlerExecutionImportMetricsOut(**dataset.import_metrics),
    )


def _now() -> datetime:
    """Return the current time as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


async def create_execution(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    execution_dispatcher: AbstractExecutionDispatcher,
    crawler_id: str,
    execution_input: CrawlerExecutionCreate | None = None,
) -> CrawlerExecutionOut:
    """Create a pending run of the published version and enqueue it.

    A seeded Context is saved in the same transaction, so the run never
    starts without it. The run is enqueued on the Crawler's queue only
    after the commit, so the worker always finds it.

    Raises:
        ValidationException: the Crawler does not exist (404), it has no
            published version (409), or the Context is invalid (400).
    """
    context = (execution_input or CrawlerExecutionCreate()).context
    errors = validate_seed_context(context)
    if errors:
        raise ValidationException("Invalid context: " + " ".join(errors), 400)

    crawler = await crawler_service.get_crawler(
        write_repositories, current_user, crawler_id
    )
    published = await write_repositories.crawler_versions.get_published_by_crawler_id(
        crawler.id
    )
    if None is published:
        raise ValidationException("Crawler has no published version to run.", 409)

    saved = await _stage_execution(
        write_repositories, published, context, crawler.queue
    )
    await write_repositories.commit()
    await execution_dispatcher.dispatch(saved.id, saved.queue)

    logger.info("Crawler execution created: id=%s, crawler_id=%s", saved.id, crawler.id)
    return _to_out(saved, crawler.title, list(context))


async def create_test_execution(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    execution_dispatcher: AbstractExecutionDispatcher,
    version_id: str,
    execution_input: CrawlerExecutionCreate | None = None,
) -> CrawlerExecutionOut:
    """Create a test run of any version and enqueue it on `testing`.

    Draft, published, or archived: the run executes exactly that
    version. It inherits the latest real run's Context like any run,
    but is never inherited from itself.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), or the Context is invalid (400).
    """
    context = (execution_input or CrawlerExecutionCreate()).context
    errors = validate_seed_context(context)
    if errors:
        raise ValidationException("Invalid context: " + " ".join(errors), 400)
    version = await write_repositories.crawler_versions.get_by_id(version_id)
    if None is version:
        raise ValidationException("Crawler version not found.", 404)
    crawler = await crawler_service.get_crawler(
        write_repositories, current_user, version.crawler_id
    )

    saved = await _stage_execution(write_repositories, version, context, TESTING_QUEUE)
    await write_repositories.commit()
    await execution_dispatcher.dispatch(saved.id, saved.queue)

    logger.info(
        "Test execution created: id=%s, crawler_id=%s, version_id=%s",
        saved.id,
        crawler.id,
        version.id,
    )
    return _to_out(saved, crawler.title, list(context))


async def create_scheduled_execution(
    write_repositories: AbstractWriteRepositories,
    execution_dispatcher: AbstractExecutionDispatcher,
    scheduled: ScheduledCrawler,
) -> str:
    """Create and enqueue a pending run for a Crawler whose cron is due.

    Returns:
        The new execution's id.
    """
    saved = await _stage_execution(
        write_repositories, scheduled.published_version, {}, scheduled.crawler.queue
    )
    await write_repositories.commit()
    await execution_dispatcher.dispatch(saved.id, saved.queue)
    logger.info(
        "Scheduled execution created: id=%s, crawler_id=%s", saved.id, saved.crawler_id
    )
    return saved.id


async def start_execution(
    write_repositories: AbstractWriteRepositories, execution_id: str
) -> bool:
    """Move a pending run to `running`.

    Returns:
        `False` when the run is gone or no longer pending (e.g. a
        redelivered task), so the worker must not run it again.
    """
    execution = await write_repositories.crawler_executions.get_by_id(execution_id)
    if None is execution or "pending" != execution.status:
        return False
    now = _now()
    await write_repositories.crawler_executions.save(
        replace(execution, status="running", started_at=now, updated_at=now)
    )
    await write_repositories.commit()
    return True


async def finish_execution(
    write_repositories: AbstractWriteRepositories,
    export_storage: AbstractDatasetExportStorage,
    execution_metrics: AbstractExecutionMetrics,
    execution_id: str,
    outcome: RunOutcome,
) -> str:
    """Save a run's Context and counters and its final status.

    Values for the Crawler's fields go to the execution's CSV, stored
    only as a file in `export_storage`; the rest replace its Context.
    The rows are validated first (DOMAIN_MODEL §5.4): parsing is
    `parsed` only when the run succeeded and the validation found
    nothing wrong. A failed export fails the run, since the file is the
    CSV's only copy; its Context, counters, and validation report are
    still saved. The run is recorded in `execution_metrics` once
    committed.

    Returns:
        The final status: `succeeded` or `failed`.
    """
    execution = await write_repositories.crawler_executions.get_by_id(execution_id)
    if None is execution:
        return "failed"
    await save_context(write_repositories, execution_id, outcome.context)
    validation, export_failure = await _save_dataset(
        write_repositories, export_storage, execution, outcome
    )
    failure = "; ".join(filter(None, (outcome.failure, export_failure))) or None
    status = "failed" if failure else "succeeded"
    now = _now()
    finished = await write_repositories.crawler_executions.save(
        replace(
            execution,
            status=status,
            parsing_status="parsed" if _is_parsed(failure, validation) else "failed",
            finished_at=now,
            updated_at=now,
            metrics={
                **execution.metrics,
                "request_count": outcome.request_count,
                "error_count": outcome.error_count,
                "retry_count": outcome.retry_count,
            },
        )
    )
    await write_repositories.commit()
    execution_metrics.record_finished(finished)
    logger.info(
        "Crawler execution finished: id=%s, status=%s, failure=%s",
        execution_id,
        status,
        failure,
    )
    return status


async def _stage_execution(
    write_repositories: AbstractWriteRepositories,
    version: CrawlerVersion,
    context: dict[str, Any],
    queue: str,
) -> CrawlerExecution:
    """Stage a pending run of `version` on `queue`, with its Context.

    It starts from the Crawler's previous run's Context, without the
    keys `version`'s selectors harvest; seeded keys replace inherited
    ones and may set a harvested key for this run. The caller commits.
    """
    inherited = drop_harvested(
        await get_last_context(write_repositories, version.crawler_id),
        await get_harvested_keys(write_repositories, version),
    )
    now = _now()
    saved = await write_repositories.crawler_executions.save(
        CrawlerExecution(
            id=str(uuid.uuid4()),
            crawler_id=version.crawler_id,
            crawler_version_id=version.id,
            status="pending",
            parsing_status="pending",
            queue=queue,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    await save_context(write_repositories, saved.id, {**inherited, **context})
    return saved


async def get_last_context(
    repositories: AbstractRepositories, crawler_id: str
) -> dict[str, Any]:
    """Return the Context of the Crawler's latest execution, or `{}`."""
    latest = await repositories.crawler_executions.get_latest_by_crawler_id(crawler_id)
    if None is latest:
        return {}
    return await get_context(repositories, latest.id)


async def get_harvested_keys(
    repositories: AbstractRepositories, version: CrawlerVersion
) -> frozenset[str]:
    """Return the Context keys `version`'s selectors write.

    A run of `version` never inherits them (DOMAIN_MODEL §4.10).
    """
    crawler = await repositories.crawlers.get_by_id(version.crawler_id)
    templates = await repositories.message_templates.get_all_by_crawler_version_id(
        version.id
    )
    selectors = [
        selector
        for template in templates
        for selector in await repositories.message_selectors.get_all_by_message_template_id(
            template.id
        )
    ]
    return harvested_keys(selectors, crawler.fields if crawler else [])


async def get_context(
    repositories: AbstractRepositories, execution_id: str
) -> dict[str, Any]:
    """Return an execution's Context, lists in position order."""
    entries = (
        await repositories.crawler_execution_contexts.get_all_by_crawler_execution_ids(
            [execution_id]
        )
    )
    return entries_to_context(
        [(entry.key, entry.position, entry.value) for entry in entries]
    )


async def save_context(
    write_repositories: AbstractWriteRepositories,
    execution_id: str,
    context: dict[str, Any],
) -> None:
    """Stage replacing an execution's whole Context; caller commits.

    Each `name[]` key becomes one entry per element; values are stored
    as primitives (objects and lists as JSON text).
    """
    contexts = write_repositories.crawler_execution_contexts
    await contexts.delete_by_crawler_execution_ids([execution_id])
    now = _now()
    await contexts.save_all(
        [
            CrawlerExecutionContext(
                id=str(uuid.uuid4()),
                crawler_execution_id=execution_id,
                key=key,
                value=value,
                position=position,
                created_at=now,
                updated_at=now,
            )
            for key, position, value in context_to_entries(context)
        ]
    )


async def _save_dataset(
    write_repositories: AbstractWriteRepositories,
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    outcome: RunOutcome,
) -> tuple[DatasetValidation, str | None]:
    """Validate the run's rows, export their CSV, record the dataset.

    The CSV goes only to `export_storage`, as raw; a parsed run's moves
    to validated. MongoDB keeps its path and the validation report.

    Returns:
        What the validation found, and why the export failed (`None`
        when the CSV was stored).
    """
    fields, rows, validation = await _validate_rows(
        write_repositories, execution, outcome
    )
    try:
        file_path = await _store_export(
            export_storage,
            execution,
            build_csv(fields, rows),
            is_parsed=_is_parsed(outcome.failure, validation),
        )
        export_failure = None
    except ExternalServiceException as exception:
        logger.warning(
            "Dataset CSV export failed: id=%s, error=%s",
            execution.id,
            exception.message,
        )
        file_path = None
        export_failure = f"Dataset CSV export failed: {exception.message}"
    now = _now()
    await write_repositories.crawler_execution_datasets.save(
        CrawlerExecutionDataset(
            id=str(uuid.uuid4()),
            crawler_execution_id=execution.id,
            fields=fields,
            file_path=file_path,
            row_count=len(rows),
            created_at=now,
            updated_at=now,
            validation=asdict(validation),
        )
    )
    return validation, export_failure


async def _validate_rows(
    write_repositories: AbstractWriteRepositories,
    execution: CrawlerExecution,
    outcome: RunOutcome,
) -> tuple[list[str], list[dict[str, Any]], DatasetValidation]:
    """Return the CSV's columns, the rows kept, and what was found.

    Without its Crawler's Dataset there are no rules to check, so the
    rows are kept as they are and the validation fails.
    """
    crawler = await write_repositories.crawlers.get_by_id(execution.crawler_id)
    fields = [] if None is crawler else crawler.fields
    dataset = (
        None
        if None is crawler
        else await write_repositories.datasets.get_by_id(crawler.dataset_id)
    )
    if None is dataset:
        return fields, outcome.dataset_rows, DatasetValidation(is_valid=False)
    rows, validation = validate_dataset_rows(outcome.dataset_rows, fields, dataset)
    return fields, rows, validation


async def _store_export(
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    csv_content: str,
    *,
    is_parsed: bool,
) -> str:
    """Export the CSV as raw; move it to validated if the run parsed.

    Returns:
        Where the CSV ended up.

    Raises:
        ExternalServiceException: the CSV could not be stored.
    """
    file_path = await export_storage.save(export_file_stem(execution), csv_content)
    if is_parsed:
        return await _move_to_validated(export_storage, execution, file_path)
    return file_path


def _is_parsed(failure: str | None, validation: DatasetValidation) -> bool:
    """Tell whether the run succeeded and its rows passed: parsed."""
    return not failure and validation.is_valid


async def _move_to_validated(
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    raw_path: str,
) -> str:
    """Return the validated CSV's path, or the raw one if moving failed.

    The CSV is still stored, in raw, so a failed move is logged and
    never changes the run or its parsing.
    """
    try:
        return await export_storage.move_to_validated(export_file_stem(execution))
    except ExternalServiceException as exception:
        logger.warning(
            "Dataset CSV move to validated failed: id=%s, error=%s",
            execution.id,
            exception.message,
        )
        return raw_path


async def get_executions(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    crawler_id: str,
    query: CrawlerExecutionHistoryQuery,
) -> CrawlerExecutionsPageOut:
    """Return one page of a Crawler's runs, newest first.

    Unlike every Crawler's runs, it paginates even when filtered: it is
    one Crawler's history. Without a queue, test runs stay out
    (`resolve_history_queues`). Fetches one extra run to tell whether
    more exist, avoiding a count query.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, crawler_id
    )
    limit, offset = resolve_page(False, query.limit, query.offset)
    executions = await read_repositories.crawler_executions.get_all_by_crawler_id(
        crawler.id,
        status=query.status,
        limit=limit + 1,
        queues=resolve_history_queues(query.queue),
        offset=offset,
    )
    page = executions[:limit]
    return CrawlerExecutionsPageOut(
        items=await _to_outs(read_repositories, page, {crawler.id: crawler.title}),
        limit=limit,
        offset=offset,
        has_more=len(executions) > limit,
    )


async def get_execution_summary(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    crawler_id: str,
    queue: str | None = None,
) -> CrawlerExecutionSummaryOut:
    """Return a Crawler's streak, success rate, and timing.

    Reads the last `SUMMARY_WINDOW` ended and successful runs; only a
    streak longer than that reads on, until it breaks
    (`_count_consecutive_successes`). Without a queue, test runs stay
    out.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, crawler_id
    )
    queues = resolve_history_queues(queue)
    executions = read_repositories.crawler_executions
    recent = await executions.get_ended_by_crawler_id(
        crawler.id, queues, SUMMARY_WINDOW
    )
    successful = await executions.get_successful_by_crawler_id(
        crawler.id, queues, SUMMARY_WINDOW
    )
    verification_failure_at, failure_at = await _get_last_failures(
        read_repositories, crawler.id, queues
    )
    return CrawlerExecutionSummaryOut(
        consecutive_successful_runs=await _count_consecutive_successes(
            read_repositories, crawler.id, queues, recent
        ),
        avg_completion_seconds=calculate_average_completion_seconds(successful),
        success_rate=calculate_success_rate(recent),
        recent_run_count=len(recent),
        last_success_at=_finished_at(successful[0] if successful else None),
        last_verification_failure_at=verification_failure_at,
        last_failure_at=failure_at,
        avg_completeness_rate=await _average_completeness(
            read_repositories, successful
        ),
    )


async def _get_last_failures(
    repositories: AbstractRepositories, crawler_id: str, queues: tuple[str, ...]
) -> tuple[datetime | None, datetime | None]:
    """Return when the last verification failure and failure ended."""
    executions = repositories.crawler_executions
    verification_failure = (
        await executions.get_latest_verification_failure_by_crawler_id(
            crawler_id, queues
        )
    )
    failure = await executions.get_latest_failure_by_crawler_id(crawler_id, queues)
    return _finished_at(verification_failure), _finished_at(failure)


def _finished_at(execution: CrawlerExecution | None) -> datetime | None:
    """Return when the run finished, or `None` without a run."""
    return None if None is execution else execution.finished_at


async def _average_completeness(
    repositories: AbstractRepositories, executions: list[CrawlerExecution]
) -> float | None:
    """Return the mean completeness rate of these runs' datasets."""
    datasets = await repositories.crawler_execution_datasets.get_summaries_by_crawler_execution_ids(
        [execution.id for execution in executions]
    )
    return calculate_average_completeness(
        (dataset.validation or {}).get("completeness_rate")
        for dataset in datasets.values()
    )


async def get_execution_history(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    crawler_id: str,
    query: CrawlerExecutionWindowQuery,
) -> CrawlerExecutionHistoryOut:
    """Return a Crawler's runs of the last `query.days` days.

    The runs stop at `HISTORY_WINDOW_MAX_RUNS`, newest first; the
    outcome counts cover the whole window. Fetches one run past the cap
    to tell whether it was reached. Without a queue, test runs stay out.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, crawler_id
    )
    queues = resolve_history_queues(query.queue)
    window_end = _now()
    window_start = window_end - timedelta(days=query.days)
    executions = read_repositories.crawler_executions
    window_runs = await executions.get_all_by_crawler_id(
        crawler.id,
        limit=HISTORY_WINDOW_MAX_RUNS + 1,
        queues=queues,
        created_since=window_start,
    )
    status_counts = await executions.count_by_status_by_crawler_id(
        crawler.id, queues, window_start
    )
    runs = window_runs[:HISTORY_WINDOW_MAX_RUNS]
    return CrawlerExecutionHistoryOut(
        runs=await _to_outs(read_repositories, runs, {crawler.id: crawler.title}),
        counts=CrawlerExecutionOutcomeCountsOut(**count_outcomes(status_counts)),
        is_truncated=len(window_runs) > len(runs),
        window_start=window_start,
        window_end=window_end,
    )


async def _count_consecutive_successes(
    repositories: AbstractRepositories,
    crawler_id: str,
    queues: tuple[str, ...],
    recent: list[CrawlerExecution],
) -> int:
    """Return the streak, reading past `recent` only while it lasts.

    `recent` is the newest `SUMMARY_WINDOW` ended runs. While every run
    read so far was successful and the last read was full, older runs
    are read `STREAK_SCAN_SIZE` at a time.
    """
    streak = count_leading_successes(recent)
    read, batch, batch_size = len(recent), recent, SUMMARY_WINDOW
    while streak == read and len(batch) == batch_size:
        batch_size = STREAK_SCAN_SIZE
        batch = await repositories.crawler_executions.get_ended_by_crawler_id(
            crawler_id, queues, batch_size, offset=read
        )
        streak += count_leading_successes(batch)
        read += len(batch)
    return streak


async def get_all_executions(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    query: CrawlerExecutionQuery,
) -> CrawlerExecutionsPageOut:
    """Return one page of every Crawler's runs, newest first.

    Filtered by status, parsing status, queue, or Crawler title, it is
    one capped page; unfiltered, it paginates. Fetches one extra run to
    tell whether more exist, avoiding a count query. Runs are shared,
    like their Crawlers, so `current_user` only proves a session.
    """
    filters = query.model_dump(exclude={"limit", "offset"}, exclude_none=True)
    limit, offset = resolve_page(bool(filters), query.limit, query.offset)
    crawler_ids = (
        None
        if None is query.crawler_title
        else await crawler_service.find_ids_by_title(
            read_repositories, query.crawler_title
        )
    )
    executions = await read_repositories.crawler_executions.get_all(
        status=query.status,
        parsing_status=query.parsing_status,
        queue=query.queue,
        crawler_ids=crawler_ids,
        limit=limit + 1,
        offset=offset,
    )
    page = executions[:limit]
    titles = await crawler_service.get_titles_by_id(
        read_repositories, [execution.crawler_id for execution in page]
    )
    return CrawlerExecutionsPageOut(
        items=await _to_outs(read_repositories, page, titles),
        limit=limit,
        offset=offset,
        has_more=len(executions) > limit,
    )


async def get_execution_csv(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    export_storage: AbstractDatasetExportStorage,
    execution_id: str,
) -> CrawlerExecutionCsvOut:
    """Return a run's dataset CSV, read from its file.

    Raises:
        ValidationException: the run, its Crawler, or its CSV does not
            exist (404); a run has a CSV only once it has finished, and
            none when exporting it failed.
        ExternalServiceException: the CSV's file is gone or unreadable.
    """
    execution = await get_execution(read_repositories, current_user, execution_id)
    dataset = (
        await read_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            execution.id
        )
    )
    if None is dataset or None is dataset.file_path:
        raise ValidationException("This run has no dataset CSV.", 404)
    return CrawlerExecutionCsvOut(
        filename=f"{execution.id}.csv",
        csv_content=await export_storage.read(dataset.file_path),
    )


async def get_execution_sample_csv(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    export_storage: AbstractDatasetExportStorage,
    execution_id: str,
) -> CrawlerExecutionCsvOut:
    """Return a run's Sample CSV, for a data quality check.

    At most `DATASET_SAMPLE_SIZE` rows, evenly spaced through the whole
    CSV, the same on every download (`domain/rules/dataset_sample.py`).
    Named like the run's CSV file, with its start time
    (`export_file_stem`), plus `-sample`.

    Raises:
        ValidationException: the run, its Crawler, or its CSV does not
            exist (404); a run has a CSV only once it has finished, and
            none when exporting it failed.
        ExternalServiceException: the CSV's file is gone or unreadable.
    """
    csv_file = await get_execution_csv(
        read_repositories, current_user, export_storage, execution_id
    )
    execution = await read_repositories.crawler_executions.get_by_id(execution_id)
    return CrawlerExecutionCsvOut(
        filename=f"{export_file_stem(execution)}-sample.csv",
        csv_content=sample_csv(csv_file.csv_content, DATASET_SAMPLE_SIZE),
    )


async def get_execution(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    execution_id: str,
) -> CrawlerExecutionOut:
    """Return one run.

    Raises:
        ValidationException: the execution or its Crawler does not exist
            (404).
    """
    execution = await read_repositories.crawler_executions.get_by_id(execution_id)
    if None is execution:
        raise ValidationException("Crawler execution not found.", 404)
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, execution.crawler_id
    )
    [execution_out] = await _to_outs(
        read_repositories, [execution], {crawler.id: crawler.title}
    )
    return execution_out


async def is_version_executed(
    repositories: AbstractRepositories, version_id: str
) -> bool:
    """Tell whether any run used this version (then it is kept)."""
    return await repositories.crawler_executions.has_any_by_crawler_version_id(
        version_id
    )


async def delete_executions_of_crawler(
    write_repositories: AbstractWriteRepositories, crawler_id: str
) -> None:
    """Stage deleting every run of a Crawler and its Context."""
    executions = await write_repositories.crawler_executions.get_all_by_crawler_id(
        crawler_id
    )
    execution_ids = [execution.id for execution in executions]
    await write_repositories.crawler_execution_contexts.delete_by_crawler_execution_ids(
        execution_ids
    )
    await write_repositories.crawler_execution_datasets.delete_by_crawler_execution_ids(
        execution_ids
    )
    await write_repositories.crawler_executions.delete_by_crawler_id(crawler_id)


async def _to_outs(
    repositories: AbstractRepositories,
    executions: list[CrawlerExecution],
    titles_by_crawler_id: dict[str, str],
) -> list[CrawlerExecutionOut]:
    """Map runs onto their API schema, with Context keys and dataset.

    Two queries whatever the number of runs, never one per run.
    """
    ids = [execution.id for execution in executions]
    keys_by_execution = await _get_context_keys(repositories, ids)
    datasets = await repositories.crawler_execution_datasets.get_summaries_by_crawler_execution_ids(
        ids
    )
    return [
        _to_out(
            execution,
            titles_by_crawler_id.get(execution.crawler_id, ""),
            keys_by_execution.get(execution.id, []),
            dataset=datasets.get(execution.id),
        )
        for execution in executions
    ]


async def _get_context_keys(
    repositories: AbstractRepositories, execution_ids: list[str]
) -> dict[str, list[str]]:
    """Return each execution's Context keys, in one query."""
    contexts = (
        await repositories.crawler_execution_contexts.get_all_by_crawler_execution_ids(
            execution_ids
        )
    )
    keys_by_execution: dict[str, dict[str, None]] = {}
    for context in contexts:
        keys_by_execution.setdefault(context.crawler_execution_id, {})[
            context.key
        ] = None
    return {
        execution_id: list(keys) for execution_id, keys in keys_by_execution.items()
    }
