from datetime import datetime, timedelta

import pytest
from night_crawler.domain.model.constants import CRAWLER_QUEUES
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.repositories import StatusCount
from night_crawler.domain.rules.execution_history import (
    RUN_OUTCOMES,
    calculate_average_completeness,
    calculate_average_completion_seconds,
    calculate_success_rate,
    count_leading_successes,
    count_outcomes,
    is_successful_run,
    resolve_history_queues,
    resolve_run_outcome,
)

START = datetime(2026, 10, 1, 12, 0, 0)


def _run(status="succeeded", parsing_status="parsed", seconds=60):
    """Return a run that took `seconds`; `None` leaves it unfinished."""
    return CrawlerExecution(
        id="run",
        crawler_id="crawler",
        crawler_version_id="version",
        status=status,
        parsing_status=parsing_status,
        queue="discovery",
        started_at=START,
        finished_at=None if None is seconds else START + timedelta(seconds=seconds),
        created_at=START,
        updated_at=START,
    )


def test_a_run_is_successful_only_when_it_succeeded_and_parsed():
    assert is_successful_run(_run())
    assert not is_successful_run(_run(parsing_status="failed"))
    assert not is_successful_run(_run(status="failed", parsing_status="failed"))
    assert not is_successful_run(_run(status="running", parsing_status="pending"))


def test_the_streak_counts_successes_back_to_the_first_other_ended_run():
    runs = [_run(), _run(), _run(status="cancelled"), _run()]

    assert 2 == count_leading_successes(runs)


def test_the_streak_skips_pending_and_running_runs():
    runs = [
        _run(status="pending", parsing_status="pending", seconds=None),
        _run(),
        _run(status="running", parsing_status="pending", seconds=None),
        _run(),
        _run(status="failed", parsing_status="failed"),
    ]

    assert 2 == count_leading_successes(runs)


def test_a_succeeded_but_unparsed_run_ends_the_streak():
    runs = [_run(), _run(parsing_status="failed"), _run(), _run()]

    assert 1 == count_leading_successes(runs)


def test_the_streak_is_zero_without_successes():
    assert 0 == count_leading_successes([])
    assert 0 == count_leading_successes(
        [_run(status="running", parsing_status="pending", seconds=None)]
    )
    assert 0 == count_leading_successes([_run(status="failed")] * 3)


def test_the_success_rate_counts_only_ended_runs():
    runs = [
        _run(status="running", parsing_status="pending", seconds=None),
        _run(),
        _run(parsing_status="failed"),
        _run(status="failed", parsing_status="failed"),
        _run(),
    ]

    assert 0.5 == calculate_success_rate(runs)


def test_the_success_rate_is_none_without_ended_runs():
    assert None is calculate_success_rate([])
    assert None is calculate_success_rate(
        [_run(status="pending", parsing_status="pending", seconds=None)]
    )


def test_the_average_completion_covers_successful_runs_only():
    runs = [
        _run(seconds=60),
        _run(status="failed", parsing_status="failed", seconds=1000),
        _run(seconds=120),
    ]

    assert 90.0 == calculate_average_completion_seconds(runs)


def test_the_average_completion_skips_runs_missing_a_timestamp():
    unstarted = _run(seconds=30)
    unstarted = CrawlerExecution(**{**unstarted.__dict__, "started_at": None})

    assert 30.0 == calculate_average_completion_seconds(
        [_run(seconds=30), _run(seconds=None), unstarted]
    )


def test_the_average_completion_is_none_without_successful_runs():
    assert None is calculate_average_completion_seconds([])
    assert None is calculate_average_completion_seconds(
        [_run(status="failed", parsing_status="failed")]
    )


def test_history_covers_every_crawler_queue_unless_one_is_asked():
    assert CRAWLER_QUEUES == resolve_history_queues(None)
    assert "testing" not in resolve_history_queues(None)
    assert ("testing",) == resolve_history_queues("testing")


@pytest.mark.parametrize(
    ("status", "parsing_status", "outcome"),
    [
        ("succeeded", "parsed", "success"),
        ("succeeded", "failed", "verification_failed"),
        ("succeeded", "pending", "verification_failed"),
        ("failed", "failed", "failed"),
        ("cancelled", "pending", "failed"),
        ("pending", "pending", "in_progress"),
        ("running", "pending", "in_progress"),
    ],
)
def test_resolve_run_outcome(status, parsing_status, outcome):
    run = _run(status=status, parsing_status=parsing_status)

    assert outcome == resolve_run_outcome(run)
    assert outcome in RUN_OUTCOMES


def test_count_outcomes_folds_status_pairs_into_outcomes():
    counts = count_outcomes(
        [
            StatusCount("succeeded", "parsed", 24),
            StatusCount("succeeded", "failed", 3),
            StatusCount("succeeded", "pending", 1),
            StatusCount("failed", "failed", 1),
            StatusCount("cancelled", "pending", 1),
            StatusCount("running", "pending", 2),
        ]
    )

    assert {
        "all": 32,
        "success": 24,
        "verification_failed": 4,
        "failed": 2,
        "in_progress": 2,
    } == counts


def test_count_outcomes_of_nothing_is_all_zero():
    assert dict.fromkeys(("all", *RUN_OUTCOMES), 0) == count_outcomes([])


def test_the_average_completeness_skips_runs_without_one():
    assert 0.9 == calculate_average_completeness([1.0, None, 0.8])
    assert None is calculate_average_completeness([None])
    assert None is calculate_average_completeness([])
