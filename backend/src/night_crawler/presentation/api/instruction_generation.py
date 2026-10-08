"""Routes asking the AI agents to write a version's instructions.

A generation runs on the `ai-agents` queue; the client polls it until
it ends, then follows its test run like any other.
"""

from typing import Literal

from fastapi import Depends, status
from fastapi.routing import APIRouter
from night_crawler.domain.ports.instruction_generation_dispatcher import (
    AbstractInstructionGenerationDispatcher,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_current_user,
    get_instruction_generation_dispatcher,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.instruction_generation import (
    InstructionGenerationCreate,
    InstructionGenerationOut,
)
from night_crawler.services import instruction_generation_service

router = APIRouter(tags=["Instruction Generations"])


@router.post(
    "/api/crawler-versions/{version_id}/instruction-generations",
    response_model=InstructionGenerationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation(
    version_id: str,
    generation_input: InstructionGenerationCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
    generation_dispatcher: AbstractInstructionGenerationDispatcher = Depends(
        get_instruction_generation_dispatcher
    ),
) -> InstructionGenerationOut:
    """Ask the AI agent to write a version's instructions.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing; 409 if the version is archived.
    """
    return await instruction_generation_service.create_generation(
        write_repositories,
        current_user,
        generation_dispatcher,
        version_id,
        generation_input,
    )


@router.get(
    "/api/instruction-generations/{generation_id}",
    response_model=InstructionGenerationOut,
)
async def get_generation(
    generation_id: str,
    include: Literal["recording"] | None = None,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> InstructionGenerationOut:
    """Get one generation, to follow it until it ends.

    `?include=recording` adds the browser agent's recording, left out
    otherwise so polling stays small.

    Raises:
        ValidationException: 404 if it or its Crawler is missing.
    """
    return await instruction_generation_service.get_generation(
        read_repositories, current_user, generation_id, "recording" == include
    )
