from unittest.mock import MagicMock

import pytest
from celery import Celery
from night_crawler.infrastructure.tasks.celery_instruction_generation_dispatcher import (
    CeleryInstructionGenerationDispatcher,
)


@pytest.mark.anyio
async def test_dispatch_sends_the_task_by_name_on_the_ai_agents_queue():
    app = MagicMock(spec=Celery)

    await CeleryInstructionGenerationDispatcher(app).dispatch("generation-1")

    app.send_task.assert_called_once_with(
        "night_crawler.tasks.generate_crawler_instructions",
        args=["generation-1"],
        queue="ai-agents",
    )
