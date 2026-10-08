"""The ports one execution run needs, opened together for one task."""

from dataclasses import dataclass

from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.bundles.request_executors import RequestExecutors
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from night_crawler.domain.ports.rate_limiter import AbstractRateLimiter


@dataclass(frozen=True)
class ExecutionInfrastructure:
    """Everything `process_execution` reaches the outside world through.

    `core/di.py` opens it for one task and closes it afterwards, so the
    worker only carries it to the service.

    Attributes:
        repository_factories: Opens short-lived repository sets.
        executors: One request executor per render mode.
        rate_limiter: Paces requests per rate-limit key.
        export_storage: Where the run's CSV is exported.
        execution_metrics: Records the run once it finishes.
    """

    repository_factories: RepositorySetFactories
    executors: RequestExecutors
    rate_limiter: AbstractRateLimiter
    export_storage: AbstractDatasetExportStorage
    execution_metrics: AbstractExecutionMetrics
