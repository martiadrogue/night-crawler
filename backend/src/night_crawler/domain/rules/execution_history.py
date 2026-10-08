"""Reading a Crawler's run history: streak, success rate, timing.

Every function takes runs newest first, as the repositories return
them. Only ended runs count; `pending` and `running` ones are skipped
(DOMAIN_MODEL §4.9).
"""

from collections.abc import Iterable

from night_crawler.domain.model.constants import CRAWLER_QUEUES
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.repositories import StatusCount

SUMMARY_WINDOW = 30
"""Ended runs the success rate covers, and successful runs averaged."""

HISTORY_WINDOW_MAX_RUNS = 1000
"""Most runs one history window returns; its counts cover them all."""

STREAK_SCAN_SIZE = 200
"""Ended runs read per query while a streak runs past the window."""

RUN_OUTCOMES: tuple[str, ...] = (
    "success",
    "verification_failed",
    "failed",
    "in_progress",
)
"""What a run came to, as its history shows it (DOMAIN_MODEL §4.9)."""

SUCCESSFUL_STATUS = "succeeded"
SUCCESSFUL_PARSING_STATUS = "parsed"
ENDED_STATUSES: tuple[str, ...] = ("succeeded", "failed", "cancelled")
FAILED_STATUSES: tuple[str, ...] = ("failed", "cancelled")


def is_successful_run(execution: CrawlerExecution) -> bool:
    """Tell whether a run succeeded and its rows passed validation."""
    return (
        SUCCESSFUL_STATUS == execution.status
        and SUCCESSFUL_PARSING_STATUS == execution.parsing_status
    )


def resolve_run_outcome(execution: CrawlerExecution) -> str:
    """Return the run's outcome, one of `RUN_OUTCOMES`.

    A succeeded run whose rows failed validation is
    `verification_failed`; a cancelled run counts as `failed`.
    """
    return outcome_of(execution.status, execution.parsing_status)


def outcome_of(status: str, parsing_status: str) -> str:
    """Return the outcome of a run in this status and parsing status."""
    if status not in ENDED_STATUSES:
        return "in_progress"
    if SUCCESSFUL_STATUS != status:
        return "failed"
    if SUCCESSFUL_PARSING_STATUS == parsing_status:
        return "success"
    return "verification_failed"


def count_outcomes(status_counts: Iterable[StatusCount]) -> dict[str, int]:
    """Return how many runs came to each outcome, and `all` of them."""
    counts = dict.fromkeys(("all", *RUN_OUTCOMES), 0)
    for status_count in status_counts:
        outcome = outcome_of(status_count.status, status_count.parsing_status)
        counts[outcome] += status_count.count
        counts["all"] += status_count.count
    return counts


def calculate_average_completeness(rates: Iterable[float | None]) -> float | None:
    """Return the mean completeness rate, skipping runs without one.

    Returns:
        A rate from 0 to 1, or `None` when no run has one.
    """
    known = [rate for rate in rates if None is not rate]
    if not known:
        return None
    return sum(known) / len(known)


def count_leading_successes(executions: Iterable[CrawlerExecution]) -> int:
    """Return how many successful runs come before any other ended one.

    A run that failed, was cancelled, or succeeded without passing
    validation ends the count.
    """
    count = 0
    for execution in _ended(executions):
        if not is_successful_run(execution):
            break
        count += 1
    return count


def calculate_success_rate(executions: Iterable[CrawlerExecution]) -> float | None:
    """Return the share of ended runs that were successful, 0 to 1.

    Returns:
        `None` when no run has ended yet.
    """
    ended = list(_ended(executions))
    if not ended:
        return None
    return sum(map(is_successful_run, ended)) / len(ended)


def calculate_average_completion_seconds(
    executions: Iterable[CrawlerExecution],
) -> float | None:
    """Return the mean `finished_at − started_at` of successful runs.

    Runs missing either timestamp are left out.

    Returns:
        Seconds, or `None` when no successful run has both.
    """
    durations = [
        (execution.finished_at - execution.started_at).total_seconds()
        for execution in executions
        if is_successful_run(execution)
        and None is not execution.started_at
        and None is not execution.finished_at
    ]
    if not durations:
        return None
    return sum(durations) / len(durations)


def resolve_history_queues(queue: str | None) -> tuple[str, ...]:
    """Return the queues a Crawler's history reads.

    Without a queue it is every queue a Crawler can run on, so test
    runs of its versions stay out, wherever its schedule sent it.
    """
    if None is queue:
        return CRAWLER_QUEUES
    return (queue,)


def _ended(executions: Iterable[CrawlerExecution]) -> Iterable[CrawlerExecution]:
    """Yield the runs that have reached a terminal status."""
    return (execution for execution in executions if execution.status in ENDED_STATUSES)
