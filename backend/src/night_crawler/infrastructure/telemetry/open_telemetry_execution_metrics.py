"""OpenTelemetry implementation of the execution metrics port."""

from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from opentelemetry.metrics import Meter

# Runs last from seconds to hours; the SDK's default buckets assume
# milliseconds.
DURATION_BUCKETS_SECONDS = (1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200)


class OpenTelemetryExecutionMetrics(AbstractExecutionMetrics):
    """Records finished runs on OpenTelemetry instruments.

    Prometheus sees them as `crawler_executions_total`,
    `crawler_execution_duration_seconds`, and
    `crawler_execution_{requests,errors,retries}_total`, labelled by
    `crawler_id` and `queue` (and `status` on the first two). Never by
    execution id: one series per run would grow without bound.
    """

    def __init__(self, meter: Meter) -> None:
        """Create the instruments on `meter`."""
        self._executions = meter.create_counter(
            "crawler.executions", description="Finished Crawler Executions."
        )
        self._duration = meter.create_histogram(
            "crawler.execution.duration",
            unit="s",
            description="From `started_at` to `finished_at`.",
            explicit_bucket_boundaries_advisory=DURATION_BUCKETS_SECONDS,
        )
        self._counters = {
            name: meter.create_counter(f"crawler.execution.{label}")
            for name, label in (
                ("request_count", "requests"),
                ("error_count", "errors"),
                ("retry_count", "retries"),
            )
        }

    def record_finished(self, execution: CrawlerExecution) -> None:
        """Count the run, its duration, and its request counters."""
        labels = {"crawler_id": execution.crawler_id, "queue": execution.queue}
        with_status = {**labels, "status": execution.status}
        self._executions.add(1, with_status)
        if None is not execution.started_at and None is not execution.finished_at:
            seconds = (execution.finished_at - execution.started_at).total_seconds()
            self._duration.record(seconds, with_status)
        for name, counter in self._counters.items():
            counter.add(execution.metrics.get(name, 0), labels)
