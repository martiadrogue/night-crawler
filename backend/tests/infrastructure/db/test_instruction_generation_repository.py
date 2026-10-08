from datetime import datetime

import pytest
from night_crawler.domain.model.entities import InstructionGeneration
from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentRecording,
    AgentRequest,
    AgentStep,
)

NOW = datetime(2026, 1, 1)

RECORDING = AgentRecording(
    steps=(
        AgentStep(
            index=0,
            action="click",
            url="https://shows.example/",
            is_success=False,
            params={"index": 3},
            target_xpath="html/body/button",
            error="Not clickable",
        ),
    ),
    requests=(
        AgentRequest(
            step_index=0,
            url="https://shows.example/api",
            method="POST",
            resource_type="xhr",
            request_headers={"Authorization": "<redacted>"},
            post_body='{"page": 1}',
            status=200,
            response_headers={"Content-Type": "application/json"},
            response_body='{"shows": []}',
            is_response_body_truncated=True,
        ),
        AgentRequest(
            step_index=0,
            url="https://tracker.example/",
            method="GET",
            failure="aborted",
        ),
    ),
    final_result=AgentFinalResult(data={"shows": [1, "a", None]}, is_success=False),
    is_truncated=True,
)


def _generation(**overrides) -> InstructionGeneration:
    defaults = {
        "id": "generation-1",
        "crawler_id": "crawler-1",
        "crawler_version_id": "version-1",
        "user_id": "user-1",
        "prompt": "shows",
        "status": "running",
        "created_at": NOW,
        "updated_at": NOW,
    }
    return InstructionGeneration(**{**defaults, **overrides})


@pytest.mark.anyio
async def test_a_recording_round_trips_as_value_objects(write_repositories):
    repository = write_repositories.instruction_generations

    saved = await repository.save(_generation(recording=RECORDING))
    loaded = await repository.get_by_id("generation-1")

    assert RECORDING == saved.recording
    assert RECORDING == loaded.recording


@pytest.mark.anyio
async def test_a_generation_without_a_recording_loads_none(write_repositories):
    repository = write_repositories.instruction_generations

    await repository.save(_generation())

    assert None is (await repository.get_by_id("generation-1")).recording
