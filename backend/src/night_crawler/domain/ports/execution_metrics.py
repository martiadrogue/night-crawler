"""The port for recording metrics about finished Crawler Executions."""

from abc import ABC, abstractmethod

from night_crawler.domain.model.entities import CrawlerExecution


class AbstractExecutionMetrics(ABC):
    """Records each finished run for monitoring (Prometheus, Grafana).

    Recording only updates in-memory instruments; exporting them is the
    adapter's business, in the background, so it never slows a run.
    """

    @abstractmethod
    def record_finished(self, execution: CrawlerExecution) -> None:
        """Record a run that just reached `succeeded` or `failed`.

        Args:
            execution: The run as saved, with `finished_at` and its
                final `metrics`.
        """
