"""Use cases for Crawler Executions: creating and inspecting runs."""

import logging
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from night_crawler.domain.bundles.execution_plan import RunOutcome, ScheduledCrawler
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.model.constants import TESTING_QUEUE
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
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.rules.context_entries import (
    context_to_entries,
    entries_to_context,
)
from night_crawler.domain.rules.dataset_export_names import export_file_stem
from night_crawler.domain.rules.dataset_rows import build_csv
from night_crawler.domain.rules.dataset_validation import validate_dataset_rows
from night_crawler.domain.rules.execution_context import validate_seed_context
from night_crawler.domain.rules.pagination import MAX_FILTERED_RESULTS, resolve_page
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_execution import (
    CrawlerExecutionCreate,
    CrawlerExecutionCsvOut,
    CrawlerExecutionMetricsOut,
    CrawlerExecutionOut,
    CrawlerExecutionQuery,
    CrawlerExecutionsPageOut,
    CrawlerExecutionValidationOut,
)
from night_crawler.services import crawler_service

logger = logging.getLogger(__name__)


def _to_out(
    execution: CrawlerExecution,
    crawler_title: str,
    context_keys: list[str],
    *,
    validation: dict[str, Any] | None = None,
) -> CrawlerExecutionOut:
    """Map an execution onto its API schema.

    Context values stay out: a seeded value may be a secret.
    `validation` is its dataset's report, once it finished.
    """
    return CrawlerExecutionOut(
        id=execution.id,
        crawler_id=execution.crawler_id,
        crawler_title=crawler_title,
        crawler_version_id=execution.crawler_version_id,
        status=execution.status,
        parsing_status=execution.parsing_status,
        queue=execution.queue,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        resume_count=execution.resume_count,
        metrics=CrawlerExecutionMetricsOut(**execution.metrics),
        context_keys=sorted(context_keys),
        validation=(
            None
            if None is validation
            else CrawlerExecutionValidationOut.model_validate(validation)
        ),
        created_at=execution.created_at,
        updated_at=execution.updated_at,
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
    execution_id: str,
    outcome: RunOutcome,
) -> str:
    """Save a run's Context and counters and its final status.

    Values for the Crawler's fields go to the execution's CSV, which is
    also exported to `export_storage`; the rest replace its Context.
    The rows are validated first (DOMAIN_MODEL §5.4): parsing is
    `parsed` only when the run succeeded and the validation found
    nothing wrong. A failed export never fails the run.

    Returns:
        The final status: `succeeded` or `failed`.
    """
    execution = await write_repositories.crawler_executions.get_by_id(execution_id)
    if None is execution:
        return "failed"
    await save_context(write_repositories, execution_id, outcome.context)
    validation = await _save_dataset(
        write_repositories, export_storage, execution, outcome
    )
    status = "failed" if outcome.failure else "succeeded"
    now = _now()
    await write_repositories.crawler_executions.save(
        replace(
            execution,
            status=status,
            parsing_status="parsed" if _is_parsed(outcome, validation) else "failed",
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
    logger.info(
        "Crawler execution finished: id=%s, status=%s, failure=%s",
        execution_id,
        status,
        outcome.failure,
    )
    return status


async def _stage_execution(
    write_repositories: AbstractWriteRepositories,
    version: CrawlerVersion,
    context: dict[str, Any],
    queue: str,
) -> CrawlerExecution:
    """Stage a pending run of `version` on `queue`, with its Context.

    It starts from the Crawler's previous run's Context; seeded keys
    replace inherited ones. The caller commits.
    """
    inherited = await get_last_context(write_repositories, version.crawler_id)
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
) -> DatasetValidation:
    """Validate the run's rows, stage the CSV of those kept, export it.

    The export is written as raw; a parsed run's moves to validated.

    Returns:
        What the validation found, also stored with the CSV.
    """
    crawler = await write_repositories.crawlers.get_by_id(execution.crawler_id)
    fields = [] if None is crawler else crawler.fields
    dataset = (
        None
        if None is crawler
        else await write_repositories.datasets.get_by_id(crawler.dataset_id)
    )
    rows, validation = (
        validate_dataset_rows(outcome.dataset_rows, fields, dataset)
        if None is not dataset
        else (outcome.dataset_rows, DatasetValidation(is_valid=False))
    )
    csv_content = build_csv(fields, rows)
    file_path = await _store_export(
        export_storage,
        execution,
        csv_content,
        is_parsed=_is_parsed(outcome, validation),
    )
    now = _now()
    await write_repositories.crawler_execution_datasets.save(
        CrawlerExecutionDataset(
            id=str(uuid.uuid4()),
            crawler_execution_id=execution.id,
            fields=fields,
            csv_content=csv_content,
            file_path=file_path,
            row_count=len(rows),
            created_at=now,
            updated_at=now,
            validation=asdict(validation),
        )
    )
    return validation


async def _store_export(
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    csv_content: str,
    *,
    is_parsed: bool,
) -> str | None:
    """Export the CSV as raw; move it to validated if the run parsed.

    Returns:
        Where the CSV ended up, or `None` when the export failed.
    """
    file_path = await _export_csv(export_storage, execution, csv_content)
    if file_path and is_parsed:
        return await _move_to_validated(export_storage, execution, file_path)
    return file_path


def _is_parsed(outcome: RunOutcome, validation: DatasetValidation) -> bool:
    """Tell whether the run succeeded and its rows passed: parsed."""
    return not outcome.failure and validation.is_valid


async def _move_to_validated(
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    raw_path: str,
) -> str:
    """Return the validated CSV's path, or the raw one if moving failed.

    The CSV stays in MongoDB and in raw, so a failed move is logged and
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


async def _export_csv(
    export_storage: AbstractDatasetExportStorage,
    execution: CrawlerExecution,
    csv_content: str,
) -> str | None:
    """Return where the CSV was exported, or `None` when it failed.

    The CSV stays in MongoDB either way, so a failed export is logged
    and the run carries on.
    """
    try:
        return await export_storage.save(export_file_stem(execution), csv_content)
    except ExternalServiceException as exception:
        logger.warning(
            "Dataset CSV export failed: id=%s, error=%s",
            execution.id,
            exception.message,
        )
        return None


async def get_executions(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    crawler_id: str,
    status: str | None = None,
) -> list[CrawlerExecutionOut]:
    """Return a Crawler's runs, newest first, capped at one page.

    Raises:
        ValidationException: the Crawler does not exist (404).
    """
    crawler = await crawler_service.get_crawler(
        read_repositories, current_user, crawler_id
    )
    executions = await read_repositories.crawler_executions.get_all_by_crawler_id(
        crawler.id, status=status, limit=MAX_FILTERED_RESULTS
    )
    ids = [execution.id for execution in executions]
    keys_by_execution = await _get_context_keys(read_repositories, ids)
    validations = await _get_validations(read_repositories, ids)
    return [
        _to_out(
            execution,
            crawler.title,
            keys_by_execution.get(execution.id, []),
            validation=validations.get(execution.id),
        )
        for execution in executions
    ]


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
    ids = [execution.id for execution in page]
    keys_by_execution = await _get_context_keys(read_repositories, ids)
    validations = await _get_validations(read_repositories, ids)
    return CrawlerExecutionsPageOut(
        items=[
            _to_out(
                execution,
                titles.get(execution.crawler_id, ""),
                keys_by_execution.get(execution.id, []),
                validation=validations.get(execution.id),
            )
            for execution in page
        ],
        limit=limit,
        offset=offset,
        has_more=len(executions) > limit,
    )


async def get_execution_csv(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    execution_id: str,
) -> CrawlerExecutionCsvOut:
    """Return a run's dataset CSV, read from MongoDB.

    Raises:
        ValidationException: the run, its Crawler, or its CSV does not
            exist (404); a run has a CSV only once it has finished.
    """
    execution = await get_execution(read_repositories, current_user, execution_id)
    dataset = (
        await read_repositories.crawler_execution_datasets.get_by_crawler_execution_id(
            execution.id
        )
    )
    if None is dataset:
        raise ValidationException("This run has no dataset CSV yet.", 404)
    return CrawlerExecutionCsvOut(
        filename=f"{execution.id}.csv", csv_content=dataset.csv_content
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
    keys_by_execution = await _get_context_keys(read_repositories, [execution.id])
    validations = await _get_validations(read_repositories, [execution.id])
    return _to_out(
        execution,
        crawler.title,
        keys_by_execution.get(execution.id, []),
        validation=validations.get(execution.id),
    )


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


async def _get_validations(
    repositories: AbstractRepositories, execution_ids: list[str]
) -> dict[str, dict[str, Any] | None]:
    """Return each execution's validation report, in one query."""
    return await repositories.crawler_execution_datasets.get_validations_by_crawler_execution_ids(
        execution_ids
    )


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
