"""Use cases for Instruction Generations: an AI agent writes a version.

A generation has a browser agent get what the prompt asks for while
its work is recorded, filters the recording down to the requests that
led to the data (`domain/rules/recording_filter.py`), has a
synthesizer write a whole instructions file from them (checked and
asked again until it is valid), imports the file like an uploaded one
(`crawler_instructions_service`), then starts a test run of the result
(`crawler_execution_service`). It runs no instructions itself, so it
is not a Crawler Execution.

The agent may take minutes: each step opens its own short transaction
and saves its progress, so a failed generation keeps what it got to.
"""

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from night_crawler.domain.bundles.instruction_generation_infrastructure import (
    InstructionGenerationInfrastructure,
)
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.bundles.synthesis_request import SynthesisRequest
from night_crawler.domain.exceptions import (
    AppException,
    BrowserAgentException,
    ValidationException,
)
from night_crawler.domain.model.entities import InstructionGeneration
from night_crawler.domain.model.value_objects import InstructionRequest
from night_crawler.domain.ports.browser_agent_recorder import (
    AgentRecording,
    FilteredRecording,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.instruction_generation_dispatcher import (
    AbstractInstructionGenerationDispatcher,
)
from night_crawler.domain.ports.instruction_synthesizer import InstructionsDraft
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.ports.user_directory import AbstractUserDirectory
from night_crawler.domain.rules.generation_recording import cap_recording
from night_crawler.domain.rules.recording_filter import (
    filter_recording,
    summarize_filtered_recording,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_instructions import CrawlerInstructionsCreate
from night_crawler.schemas.crawler_version import CrawlerVersionOut
from night_crawler.schemas.instruction_generation import (
    InstructionGenerationCreate,
    InstructionGenerationOut,
)
from night_crawler.services import (
    crawler_context_service,
    crawler_execution_service,
    crawler_instructions_service,
    crawler_service,
    user_service,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS_YAML_MAX_CHARS = 256 * 1024
"""The most of the synthesized file kept on a generation, to debug."""

FILTERED_REQUESTS_MAX_ENTRIES = 100
"""The most kept requests summarized on a generation."""

FILTERED_REQUEST_URL_MAX_CHARS = 2048
"""The most of each kept request's URL in that summary."""


def _now() -> datetime:
    """Return the current time as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def _to_out(generation: InstructionGeneration) -> InstructionGenerationOut:
    """Map a generation onto its API schema."""
    return InstructionGenerationOut.model_validate(generation)


async def create_generation(
    write_repositories: AbstractWriteRepositories,
    current_user: UserOut,
    generation_dispatcher: AbstractInstructionGenerationDispatcher,
    version_id: str,
    generation_input: InstructionGenerationCreate,
) -> InstructionGenerationOut:
    """Stage a pending generation for a version, then enqueue it.

    Raises:
        ValidationException: the version or its Crawler does not exist
            (404), or the version is archived (409).
    """
    version = await write_repositories.crawler_versions.get_by_id(version_id)
    if None is version:
        raise ValidationException("Crawler version not found.", 404)
    crawler = await crawler_service.get_crawler(
        write_repositories, current_user, version.crawler_id
    )
    if "archived" == version.status:
        raise ValidationException(
            "Cannot generate instructions for an archived crawler version.", 409
        )

    now = _now()
    saved = await write_repositories.instruction_generations.save(
        InstructionGeneration(
            id=str(uuid.uuid4()),
            crawler_id=crawler.id,
            crawler_version_id=version.id,
            user_id=current_user.id,
            prompt=generation_input.prompt,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )
    await write_repositories.commit()
    await generation_dispatcher.dispatch(saved.id)

    logger.info(
        "Instruction generation created: id=%s, crawler_id=%s, version_id=%s",
        saved.id,
        crawler.id,
        version.id,
    )
    return _to_out(saved)


async def get_generation(
    read_repositories: AbstractReadRepositories,
    current_user: UserOut,
    generation_id: str,
    is_recording_included: bool = False,
) -> InstructionGenerationOut:
    """Return one generation, for polling.

    Its recording is left out unless asked for, so polling stays
    small; it can take up to `GENERATION_RECORDING_MAX_BYTES`.

    Raises:
        ValidationException: the generation or its Crawler does not
            exist (404).
    """
    generation = await read_repositories.instruction_generations.get_by_id(
        generation_id
    )
    if None is generation:
        raise ValidationException("Instruction generation not found.", 404)
    await crawler_service.get_crawler(
        read_repositories, current_user, generation.crawler_id
    )
    if not is_recording_included:
        generation = replace(generation, recording=None)
    return _to_out(generation)


async def delete_generations_of_crawler(
    write_repositories: AbstractWriteRepositories, crawler_id: str
) -> None:
    """Stage deleting every generation of a Crawler (DM-9)."""
    await write_repositories.instruction_generations.delete_by_crawler_id(crawler_id)


async def clear_version_references(
    write_repositories: AbstractWriteRepositories, version_id: str
) -> None:
    """Stage nulling generations' references to a deleted version.

    A generation never keeps a version alive (unlike DM-10's runs).
    """
    await write_repositories.instruction_generations.clear_crawler_version_id(
        version_id
    )
    await write_repositories.instruction_generations.clear_result_version_id(version_id)


async def process_generation(
    infrastructure: InstructionGenerationInfrastructure, generation_id: str
) -> str:
    """Run one pending generation from start to finish.

    The browser agent's recording is saved, the synthesizer writes a
    file from it, the file is imported onto the targeted version (a
    published one forks a draft), then a test run of the result is
    started. The test run's outcome is its own.

    Returns:
        `succeeded`, `failed`, or `skipped` when it was not pending.

    Raises:
        Exception: an unexpected failure, after marking the generation
            failed, so the worker records it too.
    """
    repository_factories = infrastructure.repository_factories
    async with repository_factories.open_write() as write_repositories:
        generation = await _start_generation(write_repositories, generation_id)
    if None is generation:
        logger.info("Instruction generation not pending, skipped: id=%s", generation_id)
        return "skipped"
    try:
        await _generate(infrastructure, generation)
    except AppException as exception:
        return await _fail(repository_factories, generation.id, exception.message)
    except Exception as exception:
        logger.exception("Instruction generation crashed: id=%s", generation.id)
        await _fail(
            repository_factories, generation.id, f"Unexpected error: {exception}"
        )
        raise
    logger.info("Instruction generation succeeded: id=%s", generation.id)
    return "succeeded"


async def _start_generation(
    write_repositories: AbstractWriteRepositories, generation_id: str
) -> InstructionGeneration | None:
    """Move a pending generation to `running`; `None` if not pending.

    A redelivered task finds it running or ended and does nothing.
    """
    generation = await write_repositories.instruction_generations.get_by_id(
        generation_id
    )
    if None is generation or "pending" != generation.status:
        return None
    now = _now()
    started = await write_repositories.instruction_generations.save(
        replace(generation, status="running", started_at=now, updated_at=now)
    )
    await write_repositories.commit()
    return started


async def _generate(
    infrastructure: InstructionGenerationInfrastructure,
    generation: InstructionGeneration,
) -> None:
    """Record, filter, synthesize a file, import it, start a test run.

    Raises:
        AppException: any step failed; what was saved before stays.
    """
    repository_factories = infrastructure.repository_factories
    user, request = await _build_request(
        repository_factories.open_read(), infrastructure.user_directory, generation
    )
    recording = await _record(infrastructure, generation.id, request)
    filtered = await _filter(infrastructure, generation.id, recording)
    context_keys = await crawler_context_service.get_current_context_keys(
        repository_factories.open_read(), generation.crawler_id
    )
    draft, instructions = await _synthesize(
        infrastructure,
        generation.id,
        _synthesis_request(request, filtered),
        context_keys,
    )
    await _save_changes(
        repository_factories,
        generation.id,
        instructions_yaml=_cap(draft.yaml_text),
        required_context_keys=draft.required_context_keys,
        warnings=_missing_context_warnings(draft, context_keys),
    )
    version = await _import(repository_factories, user, generation, instructions)
    await _start_test_run(
        repository_factories,
        infrastructure.execution_dispatcher,
        user,
        generation.id,
        version.id,
    )


async def _record(
    infrastructure: InstructionGenerationInfrastructure,
    generation_id: str,
    request: InstructionRequest,
) -> AgentRecording:
    """Run the browser agent and save its recording, capped.

    The synthesizer gets the whole recording; only the stored copy is
    capped.

    Raises:
        ConfigurationException: the agent is not set up.
        BrowserAgentException: the agent failed; what it recorded
            until then is saved first.
    """
    try:
        recording = await infrastructure.recorder.record(request)
    except BrowserAgentException as exception:
        if None is not exception.recording:
            await _save_recording(infrastructure, generation_id, exception.recording)
        raise
    await _save_recording(infrastructure, generation_id, recording)
    return recording


async def _save_recording(
    infrastructure: InstructionGenerationInfrastructure,
    generation_id: str,
    recording: AgentRecording,
) -> None:
    """Save the recording on the generation, cut to its size cap."""
    await _save_changes(
        infrastructure.repository_factories,
        generation_id,
        recording=cap_recording(recording, infrastructure.recording_max_bytes),
    )


async def _filter(
    infrastructure: InstructionGenerationInfrastructure,
    generation_id: str,
    recording: AgentRecording,
) -> FilteredRecording:
    """Keep the requests that led to the data; save why each was kept.

    Raises:
        ValidationException: the agent did not get the data, or no
            recorded response carries it (422): nothing to write
            instructions from, so the synthesizer is never asked.
    """
    if not recording.final_result.is_success:
        raise ValidationException(
            "The browser agent did not get the requested data; there is "
            "nothing to write instructions from.",
            422,
        )
    filtered = filter_recording(recording, infrastructure.ignored_hosts)
    await _save_changes(
        infrastructure.repository_factories,
        generation_id,
        filtered_requests=summarize_filtered_recording(
            filtered, FILTERED_REQUESTS_MAX_ENTRIES, FILTERED_REQUEST_URL_MAX_CHARS
        ),
    )
    if not filtered.requests:
        raise ValidationException(
            "No recorded response carries the data the browser agent "
            "extracted; there is nothing to write instructions from.",
            422,
        )
    return filtered


def _synthesis_request(
    request: InstructionRequest, filtered: FilteredRecording
) -> SynthesisRequest:
    """Return the first synthesis attempt's request."""
    return SynthesisRequest(
        prompt=request.prompt,
        crawler_fields=request.crawler_fields,
        current_instructions_yaml=request.current_instructions_yaml,
        filtered_recording=filtered,
    )


async def _synthesize(
    infrastructure: InstructionGenerationInfrastructure,
    generation_id: str,
    synthesis_request: SynthesisRequest,
    context_keys: set[str],
) -> tuple[InstructionsDraft, CrawlerInstructionsCreate]:
    """Ask for a file until it is valid, each time with what was wrong.

    Raises:
        ValidationException: still invalid after the last attempt
            (422, every problem listed); that file is saved first.
    """
    attempt_request = synthesis_request
    for _attempt in range(infrastructure.synthesis_max_attempts):
        draft = await infrastructure.synthesizer.synthesize_instructions(
            attempt_request
        )
        instructions, problems = _check(draft, context_keys)
        if not problems:
            return draft, instructions
        attempt_request = replace(
            synthesis_request,
            previous_yaml=draft.yaml_text,
            previous_problems=tuple(problems),
        )
    await _save_changes(
        infrastructure.repository_factories,
        generation_id,
        instructions_yaml=_cap(attempt_request.previous_yaml or ""),
    )
    raise ValidationException(
        f"Instructions still invalid after {infrastructure.synthesis_max_attempts} "
        "attempts: " + "; ".join(attempt_request.previous_problems),
        422,
    )


def _check(
    draft: InstructionsDraft, context_keys: set[str]
) -> tuple[CrawlerInstructionsCreate | None, list[str]]:
    """Return the parsed file and what is wrong with it, if anything.

    Beyond the import's own checks, every placeholder must be filled:
    by a selector of the file, the Crawler's Context, or a required
    Context key the synthesizer named.
    """
    try:
        instructions = crawler_instructions_service.parse_instructions_text(
            draft.yaml_text
        )
    except ValidationException as error:
        return None, [error.message]
    known_keys = context_keys | set(draft.required_context_keys)
    return instructions, [
        *crawler_instructions_service.find_instruction_problems(instructions),
        *crawler_instructions_service.find_unknown_placeholders(
            instructions, known_keys
        ),
    ]


def _missing_context_warnings(
    draft: InstructionsDraft, context_keys: set[str]
) -> tuple[str, ...]:
    """Return a warning per required key the Context does not hold."""
    present = {key.removesuffix("[]") for key in context_keys}
    return tuple(
        f"Set {key} in the crawler's Context before running."
        for key in draft.required_context_keys
        if key not in present
    )


async def _build_request(
    read_repositories: AbstractReadRepositories,
    user_directory: AbstractUserDirectory,
    generation: InstructionGeneration,
) -> tuple[UserOut, InstructionRequest]:
    """Return who asked, and what the generation asks for.

    A disabled user still counts: the generation was asked for while
    they could act.

    Raises:
        ValidationException: the targeted version, the user, or the
            Crawler no longer exists (404).
        ExternalServiceException: the identity provider failed.
    """
    if None is generation.crawler_version_id:
        raise ValidationException("The targeted crawler version no longer exists.", 404)
    user = await user_service.get_user(user_directory, generation.user_id)
    crawler = await crawler_service.get_crawler(
        read_repositories, user, generation.crawler_id
    )
    current_yaml = await crawler_instructions_service.export_instructions_text(
        read_repositories, user, generation.crawler_version_id
    )
    return user, InstructionRequest(
        prompt=generation.prompt,
        crawler_fields=tuple(crawler.fields),
        current_instructions_yaml=current_yaml,
    )


async def _import(
    repository_factories: RepositorySetFactories,
    user: UserOut,
    generation: InstructionGeneration,
    instructions: CrawlerInstructionsCreate,
) -> CrawlerVersionOut:
    """Import the checked file; record the draft it landed on.

    Raises:
        ValidationException: the version can't take it (404, 409), or
            an aid's proxy or rate limit does not exist (404).
    """
    async with repository_factories.open_write() as write_repositories:
        version = await crawler_instructions_service.import_instructions(
            write_repositories, user, generation.crawler_version_id, instructions
        )
    await _save_changes(
        repository_factories, generation.id, result_version_id=version.id
    )
    return version


async def _start_test_run(
    repository_factories: RepositorySetFactories,
    execution_dispatcher: AbstractExecutionDispatcher,
    user: UserOut,
    generation_id: str,
    version_id: str,
) -> None:
    """Start a test run of the draft; mark the generation succeeded."""
    async with repository_factories.open_write() as write_repositories:
        execution = await crawler_execution_service.create_test_execution(
            write_repositories, user, execution_dispatcher, version_id
        )
    await _save_changes(
        repository_factories,
        generation_id,
        test_execution_id=execution.id,
        status="succeeded",
        finished_at=_now(),
    )


async def _fail(
    repository_factories: RepositorySetFactories, generation_id: str, message: str
) -> str:
    """Mark the generation failed with `message`; return `failed`."""
    await _save_changes(
        repository_factories,
        generation_id,
        status="failed",
        error=message,
        finished_at=_now(),
    )
    logger.warning(
        "Instruction generation failed: id=%s, error=%s", generation_id, message
    )
    return "failed"


async def _save_changes(
    repository_factories: RepositorySetFactories,
    generation_id: str,
    **changes: Any,
) -> None:
    """Save changes to a generation in their own short transaction.

    A generation deleted meanwhile (with its Crawler) is left alone.
    """
    async with repository_factories.open_write() as write_repositories:
        generation = await write_repositories.instruction_generations.get_by_id(
            generation_id
        )
        if None is generation:
            return
        await write_repositories.instruction_generations.save(
            replace(generation, **changes, updated_at=_now())
        )
        await write_repositories.commit()


def _cap(yaml_text: str) -> str:
    """Return the file, cut at `INSTRUCTIONS_YAML_MAX_CHARS`."""
    if len(yaml_text) <= INSTRUCTIONS_YAML_MAX_CHARS:
        return yaml_text
    return yaml_text[:INSTRUCTIONS_YAML_MAX_CHARS] + "\n# … truncated\n"
