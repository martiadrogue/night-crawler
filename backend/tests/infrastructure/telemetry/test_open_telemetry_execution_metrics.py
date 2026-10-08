from datetime import datetime

from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.infrastructure.telemetry.open_telemetry_execution_metrics import (
    OpenTelemetryExecutionMetrics,
)


def _execution(status="succeeded", started_at=datetime(2026, 1, 1, 10, 0, 0)):
    return CrawlerExecution(
        id="execution-1",
        crawler_id="crawler-1",
        crawler_version_id="version-1",
        status=status,
        parsing_status="parsed",
        queue="discovery",
        started_at=started_at,
        finished_at=datetime(2026, 1, 1, 10, 0, 30),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        metrics={
            "request_count": 4,
            "error_count": 1,
            "retry_count": 2,
            "records_skipped": 0,
        },
    )


LABELS = {"crawler_id": "crawler-1", "queue": "discovery"}


def test_counts_the_run_by_crawler_queue_and_status(meter, read_points):
    metrics = OpenTelemetryExecutionMetrics(meter)

    metrics.record_finished(_execution())
    metrics.record_finished(_execution(status="failed"))

    points = {
        attributes["status"]: point.value
        for attributes, point in read_points("crawler.executions")
    }
    assert {"succeeded": 1, "failed": 1} == points
    assert {**LABELS, "status": "failed"} == read_points("crawler.executions")[1][0]


def test_records_the_run_duration_in_seconds(meter, read_points):
    OpenTelemetryExecutionMetrics(meter).record_finished(_execution())

    [(attributes, point)] = read_points("crawler.execution.duration")
    assert {**LABELS, "status": "succeeded"} == attributes
    assert 1 == point.count
    assert 30.0 == point.sum


def test_skips_the_duration_of_a_run_that_never_started(meter, read_points):
    OpenTelemetryExecutionMetrics(meter).record_finished(_execution(started_at=None))

    assert [] == read_points("crawler.execution.duration")
    assert 1 == len(read_points("crawler.executions"))


def test_adds_the_run_counters(meter, read_points):
    OpenTelemetryExecutionMetrics(meter).record_finished(_execution())

    for name, value in (
        ("crawler.execution.requests", 4),
        ("crawler.execution.errors", 1),
        ("crawler.execution.retries", 2),
    ):
        [(attributes, point)] = read_points(name)
        assert LABELS == attributes
        assert value == point.value
