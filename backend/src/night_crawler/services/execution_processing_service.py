"""Use cases a background worker runs: scheduled dispatch and runs.

Each opens its own short-lived repository sets, since a run holds
minutes of network I/O and a transaction must not stay open that long.
"""

import logging
from datetime import datetime

from croniter import CroniterBadCronError, croniter
from night_crawler.domain.bundles.execution_infrastructure import (
    ExecutionInfrastructure,
)
from night_crawler.domain.bundles.execution_plan import RunOutcome
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.services import (
    crawler_execution_service,
    crawler_run_service,
    execution_plan_service,
)

logger = logging.getLogger(__name__)


async def dispatch_scheduled_crawlers(
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
    # Beat runs this every minute; only a dispatch that enqueued runs
    # is worth an `INFO` line.
    logger.log(
        logging.INFO if due else logging.DEBUG,
        "Scheduled dispatch complete: dispatched=%d",
        len(due),
    )
    return len(due)


async def process_execution(
    infrastructure: ExecutionInfrastructure, execution_id: str
) -> str:
    """Run one pending execution from start to finish.

    The plan is read, the requests run with no transaction open, and
    the outcome is written in a short transaction at the end, its CSV
    exported to the infrastructure's export storage.

    Returns:
        `succeeded`, `failed`, or `skipped` when the run was not
        pending.

    Raises:
        Exception: an unexpected failure, after marking the run failed,
            so the worker records it too.
    """
    repository_factories = infrastructure.repository_factories
    async with repository_factories.open_write() as write_repositories:
        if not await crawler_execution_service.start_execution(
            write_repositories, execution_id
        ):
            logger.info("Execution not pending, skipped: id=%s", execution_id)
            return "skipped"
    try:
        outcome = await _run(infrastructure, execution_id)
    except Exception as exception:
        logger.exception("Execution crashed: id=%s", execution_id)
        await _finish(infrastructure, execution_id, _crashed(exception))
        raise
    return await _finish(infrastructure, execution_id, outcome)


def _is_due(schedule: str, at: datetime) -> bool:
    """Tell whether a 5-field cron expression fires at `at`."""
    try:
        return croniter.match(schedule, at)
    except (CroniterBadCronError, ValueError):
        logger.warning("Invalid cron schedule, skipping: schedule=%s", schedule)
        return False


async def _run(
    infrastructure: ExecutionInfrastructure, execution_id: str
) -> RunOutcome:
    """Build the plan and execute it."""
    plan = await execution_plan_service.build_execution_plan(
        infrastructure.repository_factories.open_read(), execution_id
    )
    if None is plan:
        return RunOutcome(
            context={}, failure="The execution's version no longer exists."
        )
    return await crawler_run_service.execute_plan(
        infrastructure.executors, infrastructure.rate_limiter, plan
    )


async def _finish(
    infrastructure: ExecutionInfrastructure, execution_id: str, outcome: RunOutcome
) -> str:
    """Save the outcome in its own short transaction."""
    async with infrastructure.repository_factories.open_write() as write_repositories:
        return await crawler_execution_service.finish_execution(
            write_repositories,
            infrastructure.export_storage,
            infrastructure.execution_metrics,
            execution_id,
            outcome,
        )


def _crashed(exception: Exception) -> RunOutcome:
    """Return the outcome recorded for an unexpected failure."""
    return RunOutcome(context={}, failure=f"Unexpected error: {exception}")
