"""Celery implementation of the execution dispatcher port."""

from celery import Celery
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)

PROCESS_EXECUTION_TASK_NAME = "night_crawler.tasks.process_crawler_execution"


class CeleryExecutionDispatcher(AbstractExecutionDispatcher):
    """Enqueues runs by Celery task name.

    Sending by name avoids importing `presentation/worker/tasks.py`,
    which depends on `services/`; infrastructure may only depend on the
    domain.
    """

    def __init__(self, app: Celery) -> None:
        """Send tasks through the given Celery app."""
        self._app = app

    async def dispatch(self, execution_id: str, queue: str) -> None:
        """Enqueue `process_crawler_execution` onto `queue`."""
        self._app.send_task(
            PROCESS_EXECUTION_TASK_NAME, args=[execution_id], queue=queue
        )
