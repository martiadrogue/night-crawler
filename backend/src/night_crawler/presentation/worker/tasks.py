"""Celery tasks: scheduled dispatch and execution runs.

The tasks are thin: each opens its own infrastructure through
`core/di.py` and calls an `_async` function that takes it as arguments,
so the logic runs in tests without Celery or RabbitMQ.
"""

import asyncio
import logging
from datetime import UTC, datetime

from croniter import CroniterBadCronError, croniter
from night_crawler.celery import app
from night_crawler.core.di import (
    create_dataset_export_storage,
    create_execution_dispatcher,
    create_rate_limiter,
    create_request_executors,
    open_task_repositories,
)
from night_crawler.domain.bundles.execution_plan import RunOutcome
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter
from night_crawler.services import (
    crawler_execution_service,
    crawler_run_service,
    execution_plan_service,
)

logger = logging.getLogger(__name__)


def _is_due(schedule: str, at: datetime) -> bool:
    """Tell whether a 5-field cron expression fires at `at`."""
    try:
        return croniter.match(schedule, at)
    except (CroniterBadCronError, ValueError):
        logger.warning("Invalid cron schedule, skipping: schedule=%s", schedule)
        return False


async def dispatch_scheduled_crawlers_async(
    repository_factories: RepositorySetFactories,
    execution_dispatcher: AbstractExecutionDispatcher,
    now: datetime,
) -> int:
    """Create and enqueue a run for every Crawler whose cron is due.

    Each run goes to its Crawler's queue.

    Returns:
        How many runs were enqueued.
    """
    due = [
        scheduled
        for scheduled in await execution_plan_service.get_scheduled_crawlers(
            repository_factories.open_read()
        )
        if _is_due(scheduled.crawler.schedule, now)
    ]
    for scheduled in due:
        async with repository_factories.open_write() as write_repositories:
            await crawler_execution_service.create_scheduled_execution(
                write_repositories, execution_dispatcher, scheduled
            )
    logger.info("Scheduled dispatch complete: dispatched=%d", len(due))
    return len(due)


async def process_crawler_execution_async(
    repository_factories: RepositorySetFactories,
    executors: RequestExecutors,
    rate_limiter: AbstractRateLimiter,
    export_storage: AbstractDatasetExportStorage,
    execution_id: str,
) -> str:
    """Run one pending execution from start to finish.

    The plan is read, the requests run with no transaction open, and
    the outcome is written in a short transaction at the end, its CSV
    exported to `export_storage`.

    Returns:
        `succeeded`, `failed`, or `skipped` when the run was not
        pending.

    Raises:
        Exception: an unexpected failure, after marking the run failed,
            so Celery records it too.
    """
    async with repository_factories.open_write() as write_repositories:
        if not await crawler_execution_service.start_execution(
            write_repositories, execution_id
        ):
            logger.info("Execution not pending, skipped: id=%s", execution_id)
            return "skipped"
    try:
        outcome = await _run(
            repository_factories, executors, rate_limiter, execution_id
        )
    except Exception as exception:
        logger.exception("Execution crashed: id=%s", execution_id)
        await _finish(
            repository_factories, export_storage, execution_id, _crashed(exception)
        )
        raise
    return await _finish(repository_factories, export_storage, execution_id, outcome)


async def _run(
    repository_factories: RepositorySetFactories,
    executors: RequestExecutors,
    rate_limiter: AbstractRateLimiter,
    execution_id: str,
) -> RunOutcome:
    """Build the plan and execute it."""
    plan = await execution_plan_service.build_execution_plan(
        repository_factories.open_read(), execution_id
    )
    if None is plan:
        return RunOutcome(
            context={}, failure="The execution's version no longer exists."
        )
    return await crawler_run_service.execute_plan(executors, rate_limiter, plan)


async def _finish(
    repository_factories: RepositorySetFactories,
    export_storage: AbstractDatasetExportStorage,
    execution_id: str,
    outcome: RunOutcome,
) -> str:
    """Save the outcome in its own short transaction."""
    async with repository_factories.open_write() as write_repositories:
        return await crawler_execution_service.finish_execution(
            write_repositories, export_storage, execution_id, outcome
        )


def _crashed(exception: Exception) -> RunOutcome:
    """Return the outcome recorded for an unexpected failure."""
    return RunOutcome(context={}, failure=f"Unexpected error: {exception}")


async def _dispatch_scheduled_crawlers() -> int:
    """Open the task's infrastructure and dispatch due Crawlers."""
    async with open_task_repositories() as repository_factories:
        return await dispatch_scheduled_crawlers_async(
            repository_factories,
            create_execution_dispatcher(),
            datetime.now(UTC).replace(tzinfo=None),
        )


async def _process_crawler_execution(execution_id: str) -> str:
    """Open the task's infrastructure and run one execution."""
    executors = create_request_executors()
    rate_limiter = create_rate_limiter()
    try:
        async with open_task_repositories() as repository_factories:
            return await process_crawler_execution_async(
                repository_factories,
                executors,
                rate_limiter,
                create_dataset_export_storage(),
                execution_id,
            )
    finally:
        await executors.aclose()
        await rate_limiter.aclose()


@app.task(name="night_crawler.tasks.dispatch_scheduled_crawlers")
def dispatch_scheduled_crawlers() -> int:
    """Run the scheduled dispatch from Celery Beat."""
    return asyncio.run(_dispatch_scheduled_crawlers())


@app.task(name="night_crawler.tasks.process_crawler_execution")
def process_crawler_execution(execution_id: str) -> str:
    """Run one execution on the queue it was sent to."""
    return asyncio.run(_process_crawler_execution(execution_id))
