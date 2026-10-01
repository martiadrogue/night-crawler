"""The port for handing a Crawler Execution to a worker."""

from abc import ABC, abstractmethod


class AbstractExecutionDispatcher(ABC):
    """Enqueues execution runs onto a named execution queue."""

    @abstractmethod
    async def dispatch(self, execution_id: str, queue: str) -> None:
        """Enqueue one run of an execution.

        Args:
            execution_id: The pending Crawler Execution to run.
            queue: One of `EXECUTION_QUEUES`.
        """
