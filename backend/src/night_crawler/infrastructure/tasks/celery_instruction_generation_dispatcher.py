"""Celery implementation of the instruction generation dispatcher."""

from celery import Celery
from night_crawler.domain.model.constants import AI_AGENTS_QUEUE
from night_crawler.domain.ports.instruction_generation_dispatcher import (
    AbstractInstructionGenerationDispatcher,
)

GENERATE_INSTRUCTIONS_TASK_NAME = "night_crawler.tasks.generate_crawler_instructions"


class CeleryInstructionGenerationDispatcher(AbstractInstructionGenerationDispatcher):
    """Enqueues generations by Celery task name on `ai-agents`.

    Sending by name avoids importing `presentation/worker/tasks.py`,
    which depends on `services/`; infrastructure may only depend on the
    domain.
    """

    def __init__(self, app: Celery) -> None:
        """Send tasks through the given Celery app."""
        self._app = app

    async def dispatch(self, generation_id: str) -> None:
        """Enqueue `generate_crawler_instructions` onto `ai-agents`."""
        self._app.send_task(
            GENERATE_INSTRUCTIONS_TASK_NAME, args=[generation_id], queue=AI_AGENTS_QUEUE
        )
