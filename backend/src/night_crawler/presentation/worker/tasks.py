"""Celery tasks: scheduled dispatch, execution runs, AI generations.

Each task only opens its infrastructure through `core/di.py` and hands
it, unchanged, to one `services/` function (CONTRIBUTING R1.1.5).
"""

import asyncio
from datetime import UTC, datetime

from night_crawler.celery import app
from night_crawler.core.di import (
    create_execution_dispatcher,
    open_execution_infrastructure,
    open_instruction_generation_infrastructure,
    open_task_repositories,
)
from night_crawler.core.logging import bind_execution_id, bind_generation_id
from night_crawler.services import (
    execution_processing_service,
    instruction_generation_service,
)


async def _dispatch_scheduled_crawlers() -> int:
    """Open the task's repositories and dispatch due Crawlers."""
    async with open_task_repositories() as repository_factories:
        return await execution_processing_service.dispatch_scheduled_crawlers(
            repository_factories,
            create_execution_dispatcher(),
            datetime.now(UTC).replace(tzinfo=None),
        )


async def _process_crawler_execution(execution_id: str) -> str:
    """Open the run's infrastructure and process one execution.

    Every line logged during the run carries its `execution_id`, so
    Loki can show one run's story on its own.
    """
    with bind_execution_id(execution_id):
        async with open_execution_infrastructure() as infrastructure:
            return await execution_processing_service.process_execution(
                infrastructure, execution_id
            )


async def _generate_crawler_instructions(generation_id: str) -> str:
    """Open the generation's infrastructure and process it.

    Every line logged meanwhile carries its `generation_id`.
    """
    with bind_generation_id(generation_id):
        async with open_instruction_generation_infrastructure() as infrastructure:
            return await instruction_generation_service.process_generation(
                infrastructure, generation_id
            )


@app.task(name="night_crawler.tasks.dispatch_scheduled_crawlers")
def dispatch_scheduled_crawlers() -> int:
    """Run the scheduled dispatch from Celery Beat."""
    return asyncio.run(_dispatch_scheduled_crawlers())


@app.task(name="night_crawler.tasks.process_crawler_execution")
def process_crawler_execution(execution_id: str) -> str:
    """Run one execution on the queue it was sent to."""
    return asyncio.run(_process_crawler_execution(execution_id))


@app.task(name="night_crawler.tasks.generate_crawler_instructions")
def generate_crawler_instructions(generation_id: str) -> str:
    """Run one Instruction Generation on the `ai-agents` queue."""
    return asyncio.run(_generate_crawler_instructions(generation_id))
