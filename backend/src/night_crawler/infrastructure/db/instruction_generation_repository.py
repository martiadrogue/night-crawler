"""MongoDB storage for Instruction Generations."""

from dataclasses import replace
from typing import Any

from night_crawler.domain.model.entities import InstructionGeneration
from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentRecording,
    AgentRequest,
    AgentStep,
    FilteredRequestSummary,
)
from night_crawler.domain.ports.repositories import (
    AbstractInstructionGenerationRepository,
)
from night_crawler.infrastructure.db.mongo_repository import MongoRepository


class MongoInstructionGenerationRepository(
    MongoRepository[InstructionGeneration], AbstractInstructionGenerationRepository
):
    """MongoDB storage for Instruction Generations."""

    entity_type = InstructionGeneration
    collection_name = "instruction_generations"

    def _to_domain(self, document: dict[str, Any]) -> InstructionGeneration:
        """Map a document onto a generation, its recording included."""
        generation = super()._to_domain(document)
        recording = generation.recording
        return replace(
            generation,
            recording=None if None is recording else _to_recording(recording),
            filtered_requests=tuple(
                FilteredRequestSummary(
                    **{**db_request, "reasons": tuple(db_request["reasons"])}
                )
                for db_request in generation.filtered_requests
            ),
            required_context_keys=tuple(generation.required_context_keys),
            warnings=tuple(generation.warnings),
        )

    async def get_by_id(self, generation_id: str) -> InstructionGeneration | None:
        """Return the generation with this id, if any."""
        return await self._find_one({"_id": generation_id})

    async def save(self, generation: InstructionGeneration) -> InstructionGeneration:
        """Insert or update a generation; return a fresh copy."""
        return await self._save(generation)

    async def delete_by_crawler_id(self, crawler_id: str) -> None:
        """Delete every generation of a Crawler."""
        await self._delete_many({"crawler_id": crawler_id})

    async def clear_crawler_version_id(self, version_id: str) -> None:
        """Null every `crawler_version_id` equal to `version_id`."""
        await self._clear_reference("crawler_version_id", version_id)

    async def clear_result_version_id(self, version_id: str) -> None:
        """Null every `result_version_id` equal to `version_id`."""
        await self._clear_reference("result_version_id", version_id)


def _to_recording(db_recording: dict[str, Any]) -> AgentRecording:
    """Map a stored recording back onto its value objects."""
    return AgentRecording(
        steps=tuple(AgentStep(**db_step) for db_step in db_recording["steps"]),
        requests=tuple(
            AgentRequest(**db_request) for db_request in db_recording["requests"]
        ),
        final_result=AgentFinalResult(**db_recording["final_result"]),
        is_truncated=db_recording["is_truncated"],
    )
