from dataclasses import replace
from datetime import datetime

import pytest
from night_crawler.domain.bundles.instruction_generation_infrastructure import (
    InstructionGenerationInfrastructure,
)
from night_crawler.domain.bundles.synthesis_request import SynthesisRequest
from night_crawler.domain.exceptions import (
    BrowserAgentException,
    ConfigurationException,
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.model.constants import TESTING_QUEUE
from night_crawler.domain.model.value_objects import InstructionRequest
from night_crawler.domain.ports.browser_agent_recorder import (
    AbstractBrowserAgentRecorder,
    AgentFinalResult,
    AgentRecording,
    AgentRequest,
    AgentStep,
)
from night_crawler.domain.ports.instruction_generation_dispatcher import (
    AbstractInstructionGenerationDispatcher,
)
from night_crawler.domain.ports.instruction_synthesizer import (
    AbstractInstructionSynthesizer,
    InstructionsDraft,
)
from night_crawler.domain.rules.generation_recording import measure_recording
from night_crawler.schemas.instruction_generation import (
    AgentRecordingOut,
    InstructionGenerationCreate,
)
from night_crawler.services import (
    crawler_service,
    crawler_version_service,
    instruction_generation_service,
)

NOW = datetime(2026, 1, 1)

SYNTHESIS_MAX_ATTEMPTS = 3

GENERATED_YAML = """\
templates:
  search:
    action: GET
    url: https://example.com/?q=shows
aids:
  search:
    render_mode: playwright
selectors:
  results:
    template: search
    type: iterator
    path: //li
  name:
    template: search
    parent: results
    type: value
    path: ./h2
    title: name
"""


class RecordingGenerationDispatcher(AbstractInstructionGenerationDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, generation_id: str) -> None:
        self.dispatched.append(generation_id)


RECORDING = AgentRecording(
    steps=(
        AgentStep(
            index=0,
            action="navigate",
            url="https://example.com/?q=shows",
            is_success=True,
            params={"url": "https://example.com/?q=shows"},
        ),
    ),
    requests=(
        AgentRequest(
            step_index=0,
            url="https://example.com/?q=shows",
            method="GET",
            resource_type="document",
            status=200,
            response_headers={"Content-Type": "text/html"},
            response_body="<ul><li><h2>Comedy night</h2></li></ul>",
        ),
        AgentRequest(
            step_index=0,
            url="https://example.com/api/shows",
            method="GET",
            resource_type="xhr",
            status=200,
            response_body='{"shows": ["Comedy night"]}' * 20,
        ),
    ),
    final_result=AgentFinalResult(data=[{"name": "Comedy night"}], is_success=True),
)


class FixedRecorder(AbstractBrowserAgentRecorder):
    """Returns `recording`, or raises `error`; keeps every request."""

    def __init__(self, recording: AgentRecording = RECORDING, error=None) -> None:
        self.recording = recording
        self.error = error
        self.requests: list[InstructionRequest] = []

    async def record(self, request: InstructionRequest) -> AgentRecording:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.recording


class FixedSynthesizer(AbstractInstructionSynthesizer):
    """Answers `yaml_texts` in turn (the last one again once used up),
    or raises `error`; keeps every request it was given.

    `on_call`, when set, runs first, so a test can look at what was
    stored before synthesis started.
    """

    def __init__(
        self,
        *yaml_texts: str,
        error=None,
        on_call=None,
        required_context_keys: tuple[str, ...] = (),
    ):
        self.yaml_texts = list(yaml_texts) or [GENERATED_YAML]
        self.error = error
        self.on_call = on_call
        self.required_context_keys = required_context_keys
        self.calls: list[SynthesisRequest] = []

    async def synthesize_instructions(
        self, request: SynthesisRequest
    ) -> InstructionsDraft:
        self.calls.append(request)
        if self.on_call:
            await self.on_call()
        if self.error:
            raise self.error
        yaml_text = self.yaml_texts[min(len(self.calls), len(self.yaml_texts)) - 1]
        return InstructionsDraft(
            yaml_text=yaml_text, required_context_keys=self.required_context_keys
        )


@pytest.fixture
def generation_dispatcher() -> RecordingGenerationDispatcher:
    return RecordingGenerationDispatcher()


@pytest.fixture
def stored_member(user_directory, member):
    """The member as a directory account: the worker loads who asked."""
    user_directory.add(member.id, member.email, member.role)
    return member


async def _draft(write_repositories, create_crawler):
    crawler = await create_crawler()
    [draft] = await write_repositories.crawler_versions.get_all_by_crawler_id(
        crawler.id
    )
    return crawler, draft


async def _create(write_repositories, member, dispatcher, version_id, prompt="x"):
    return await instruction_generation_service.create_generation(
        write_repositories,
        member,
        dispatcher,
        version_id,
        InstructionGenerationCreate(prompt=prompt),
    )


async def _process(
    user_directory,
    repository_factories,
    execution_dispatcher,
    synthesizer,
    generation_id,
    recorder=None,
    recording_max_bytes=1024 * 1024,
):
    return await instruction_generation_service.process_generation(
        InstructionGenerationInfrastructure(
            repository_factories=repository_factories,
            user_directory=user_directory,
            recorder=recorder or FixedRecorder(),
            synthesizer=synthesizer,
            execution_dispatcher=execution_dispatcher,
            recording_max_bytes=recording_max_bytes,
            synthesis_max_attempts=SYNTHESIS_MAX_ATTEMPTS,
            ignored_hosts=("google-analytics.com",),
        ),
        generation_id,
    )


def _out(recording: AgentRecording) -> AgentRecordingOut:
    """Return the recording as the API returns it."""
    return AgentRecordingOut.model_validate(recording)


async def _get(read_repositories, member, generation_id):
    """Return the generation with its recording."""
    return await instruction_generation_service.get_generation(
        read_repositories, member, generation_id, is_recording_included=True
    )


# --- create / get -------------------------------------------------------------
@pytest.mark.anyio
async def test_create_stages_a_pending_job_and_dispatches_it(
    write_repositories, member, create_crawler, generation_dispatcher
):
    crawler, draft = await _draft(write_repositories, create_crawler)

    generation = await _create(
        write_repositories, member, generation_dispatcher, draft.id, "  shows  "
    )

    assert "pending" == generation.status
    assert "shows" == generation.prompt
    assert crawler.id == generation.crawler_id
    assert draft.id == generation.crawler_version_id
    assert member.id == generation.user_id
    assert [generation.id] == generation_dispatcher.dispatched


@pytest.mark.anyio
async def test_create_refuses_an_archived_version(
    write_repositories, member, create_crawler, generation_dispatcher
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    second = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, second.id
    )

    with pytest.raises(ValidationException) as exc_info:
        await _create(write_repositories, member, generation_dispatcher, draft.id)

    assert 409 == exc_info.value.status_code
    assert [] == generation_dispatcher.dispatched


@pytest.mark.anyio
async def test_create_and_get_refuse_unknown_ids(
    write_repositories, read_repositories, member, generation_dispatcher
):
    with pytest.raises(ValidationException) as created:
        await _create(write_repositories, member, generation_dispatcher, "missing")
    with pytest.raises(ValidationException) as fetched:
        await instruction_generation_service.get_generation(
            read_repositories, member, "missing"
        )

    assert 404 == created.value.status_code
    assert 404 == fetched.value.status_code


# --- process ------------------------------------------------------------------
@pytest.mark.anyio
async def test_process_imports_the_draft_and_starts_a_test_run(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id, "shows"
    )
    recorder = FixedRecorder()
    synthesizer = FixedSynthesizer()

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
        recorder,
    )

    generation = await instruction_generation_service.get_generation(
        read_repositories, stored_member, created.id
    )
    templates = await read_repositories.message_templates.get_all_by_crawler_version_id(
        draft.id
    )
    execution = await read_repositories.crawler_executions.get_by_id(
        generation.test_execution_id
    )
    assert "succeeded" == status
    assert "succeeded" == generation.status
    assert draft.id == generation.result_version_id
    assert GENERATED_YAML == generation.instructions_yaml
    assert None is not generation.started_at and None is not generation.finished_at
    assert ["https://example.com/?q=shows"] == [t.url for t in templates]
    assert TESTING_QUEUE == execution.queue
    assert draft.id == execution.crawler_version_id
    assert [(execution.id, TESTING_QUEUE)] == execution_dispatcher.dispatched
    [request] = recorder.requests
    assert "shows" == request.prompt
    assert tuple(crawler.fields) == request.crawler_fields
    assert "format: night-crawler/instructions/v1" in request.current_instructions_yaml
    [synthesis] = synthesizer.calls
    document, api = RECORDING.requests
    assert ("shows", tuple(crawler.fields)) == (
        synthesis.prompt,
        synthesis.crawler_fields,
    )
    assert request.current_instructions_yaml == synthesis.current_instructions_yaml
    assert (None, ()) == (synthesis.previous_yaml, synthesis.previous_problems)
    assert [document.url, api.url] == [
        kept.request.url for kept in synthesis.filtered_recording.requests
    ]
    assert [
        ("GET", document.url, 200, (f"loads the page for {api.url}",)),
        ("GET", api.url, 200, ("carries final data",)),
    ] == [
        (f.method, f.url, f.status, tuple(f.reasons))
        for f in generation.filtered_requests
    ]
    assert ([], []) == (generation.required_context_keys, generation.warnings)


@pytest.mark.anyio
async def test_process_on_a_published_version_lands_on_a_new_draft(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    published = await crawler_version_service.publish_draft(
        write_repositories, stored_member, crawler.id, draft.id
    )
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, published.id
    )

    await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(),
        created.id,
    )

    generation = await instruction_generation_service.get_generation(
        read_repositories, stored_member, created.id
    )
    kept = await read_repositories.message_templates.get_all_by_crawler_version_id(
        published.id
    )
    assert "succeeded" == generation.status
    assert published.id != generation.result_version_id
    assert [""] == [template.url for template in kept]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("templates: [unclosed", "not valid YAML"),
        ("base: &b {action: GET, url: x}\ntemplates:\n  a: *b", "aliases"),
        ("templates:\n  a: {action: FETCH, url: x}", "templates.a.action"),
        (
            (
                "templates:\n  a: {action: GET, url: x}\n"
                "selectors:\n  s: {template: missing, type: value, path: x}"
            ),
            "selectors.s",
        ),
    ],
)
async def test_process_fails_on_a_bad_file_and_leaves_the_draft(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
    yaml_text,
    message,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(yaml_text),
        created.id,
    )

    generation = await instruction_generation_service.get_generation(
        read_repositories, stored_member, created.id
    )
    templates = await read_repositories.message_templates.get_all_by_crawler_version_id(
        draft.id
    )
    assert "failed" == status
    assert "failed" == generation.status
    assert message in generation.error
    assert yaml_text == generation.instructions_yaml
    assert None is generation.result_version_id
    assert [draft.message_template_root_id] == [template.id for template in templates]
    assert [] == execution_dispatcher.dispatched


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ExternalServiceException("Gemini is down."), "Gemini is down."),
        (
            ConfigurationException("Instruction synthesis not configured."),
            "Instruction synthesis not configured.",
        ),
    ],
)
async def test_process_fails_when_the_synthesizer_raises(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
    error,
    message,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(error=error),
        created.id,
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "failed" == status
    assert message == generation.error
    assert None is not generation.finished_at
    assert _out(RECORDING) == generation.recording


@pytest.mark.anyio
async def test_process_saves_the_recording_before_synthesis(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )
    seen = []

    async def look_at_the_stored_generation():
        seen.append(
            await _get(repository_factories.open_read(), stored_member, created.id)
        )

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(on_call=look_at_the_stored_generation),
        created.id,
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "succeeded" == status
    assert [_out(RECORDING)] == [generation.recording for generation in seen]
    assert _out(RECORDING) == generation.recording
    assert not generation.recording.is_truncated


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "kept"),
    [
        (BrowserAgentException("Browser agent timed out after 5 s.", RECORDING), True),
        (BrowserAgentException("Browser agent failed: RuntimeError.", None), False),
        (ConfigurationException("GEMINI_API_KEY must be set."), False),
    ],
)
async def test_process_fails_when_the_recorder_fails(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
    error,
    kept,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )
    synthesizer = FixedSynthesizer()

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
        FixedRecorder(error=error),
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "failed" == status
    assert error.message == generation.error
    assert (_out(RECORDING) if kept else None) == generation.recording
    assert [] == synthesizer.calls


@pytest.mark.anyio
async def test_process_caps_the_stored_recording_bodies_first(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )
    synthesizer = FixedSynthesizer()

    await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
        recording_max_bytes=measure_recording(RECORDING) - 100,
    )

    generation = await _get(read_repositories, stored_member, created.id)
    document, api = generation.recording.requests
    assert generation.recording.is_truncated
    assert None is not document.response_body
    assert (None, True) == (api.response_body, api.is_response_body_truncated)
    [synthesis] = synthesizer.calls
    assert RECORDING.requests[1] == synthesis.filtered_recording.requests[-1].request


@pytest.mark.anyio
async def test_get_leaves_the_recording_out_unless_asked(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )
    await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(),
        created.id,
    )

    polled = await instruction_generation_service.get_generation(
        read_repositories, stored_member, created.id
    )
    asked = await _get(read_repositories, stored_member, created.id)

    assert None is polled.recording
    assert _out(RECORDING) == asked.recording


# --- filtering and synthesis checks ------------------------------------------
UNKNOWN_PLACEHOLDER_YAML = GENERATED_YAML.replace("?q=shows", "?q={{query}}")

CREDENTIAL_YAML = GENERATED_YAML.replace(
    "    url: https://example.com/?q=shows\n",
    "    url: https://example.com/?q=shows\n"
    "    headers:\n      Authorization: '{{authorization}}'\n",
)


async def _pending(write_repositories, stored_member, create_crawler, dispatcher):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(write_repositories, stored_member, dispatcher, draft.id)
    return draft, created


@pytest.mark.anyio
async def test_invalid_then_valid_sends_the_problems_back(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _draft_version, created = await _pending(
        write_repositories, stored_member, create_crawler, generation_dispatcher
    )
    synthesizer = FixedSynthesizer("templates: [unclosed", GENERATED_YAML)

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
    )

    first, second = synthesizer.calls
    assert "succeeded" == status
    assert (None, ()) == (first.previous_yaml, first.previous_problems)
    assert "templates: [unclosed" == second.previous_yaml
    [problem] = second.previous_problems
    assert "not valid YAML" in problem


@pytest.mark.anyio
async def test_always_invalid_fails_with_the_problems_and_keeps_the_last_file(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _draft_version, created = await _pending(
        write_repositories, stored_member, create_crawler, generation_dispatcher
    )
    synthesizer = FixedSynthesizer("templates: [unclosed", UNKNOWN_PLACEHOLDER_YAML)

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "failed" == status
    assert SYNTHESIS_MAX_ATTEMPTS == len(synthesizer.calls)
    assert generation.error.startswith(
        f"Instructions still invalid after {SYNTHESIS_MAX_ATTEMPTS} attempts:"
    )
    assert "templates.search: placeholder `query`" in generation.error
    assert UNKNOWN_PLACEHOLDER_YAML == generation.instructions_yaml
    assert None is generation.result_version_id
    assert [] == execution_dispatcher.dispatched


@pytest.mark.anyio
async def test_an_unknown_placeholder_is_a_problem(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _draft_version, created = await _pending(
        write_repositories, stored_member, create_crawler, generation_dispatcher
    )
    synthesizer = FixedSynthesizer(UNKNOWN_PLACEHOLDER_YAML, GENERATED_YAML)

    await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
    )

    [problem] = synthesizer.calls[1].previous_problems
    assert (
        "templates.search: placeholder `query` is neither harvested by a "
        "selector titled `query` nor in the Crawler's Context"
    ) == problem


@pytest.mark.anyio
async def test_a_required_key_missing_from_the_context_still_runs_with_a_warning(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _draft_version, created = await _pending(
        write_repositories, stored_member, create_crawler, generation_dispatcher
    )
    synthesizer = FixedSynthesizer(
        CREDENTIAL_YAML, required_context_keys=("authorization",)
    )

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "succeeded" == status
    assert 1 == len(synthesizer.calls)
    assert ["authorization"] == generation.required_context_keys
    assert [
        "Set authorization in the crawler's Context before running."
    ] == generation.warnings
    assert None is not generation.test_execution_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("final_result", "message"),
    [
        (
            AgentFinalResult(data=[{"name": "Nowhere to be seen"}], is_success=True),
            "No recorded response carries the data the browser agent extracted",
        ),
        (
            AgentFinalResult(data=[{"name": "Comedy night"}], is_success=False),
            "The browser agent did not get the requested data",
        ),
    ],
)
async def test_no_chain_fails_before_synthesis(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
    final_result,
    message,
):
    _draft_version, created = await _pending(
        write_repositories, stored_member, create_crawler, generation_dispatcher
    )
    synthesizer = FixedSynthesizer()

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
        FixedRecorder(replace(RECORDING, final_result=final_result)),
    )

    generation = await _get(read_repositories, stored_member, created.id)
    assert "failed" == status
    assert generation.error.startswith(message)
    assert [] == synthesizer.calls
    assert None is not generation.recording


@pytest.mark.anyio
async def test_process_skips_a_job_that_is_not_pending(
    user_directory,
    write_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )
    await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        FixedSynthesizer(),
        created.id,
    )
    recorder = FixedRecorder()
    synthesizer = FixedSynthesizer()

    status = await _process(
        user_directory,
        repository_factories,
        execution_dispatcher,
        synthesizer,
        created.id,
        recorder,
    )

    assert "skipped" == status
    assert [] == recorder.requests


@pytest.mark.anyio
async def test_process_marks_a_crash_failed_and_reraises(
    user_directory,
    write_repositories,
    read_repositories,
    repository_factories,
    stored_member,
    create_crawler,
    generation_dispatcher,
    execution_dispatcher,
):
    _crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(
        write_repositories, stored_member, generation_dispatcher, draft.id
    )

    with pytest.raises(RuntimeError):
        await _process(
            user_directory,
            repository_factories,
            execution_dispatcher,
            FixedSynthesizer(error=RuntimeError("boom")),
            created.id,
        )

    generation = await instruction_generation_service.get_generation(
        read_repositories, stored_member, created.id
    )
    assert "failed" == generation.status
    assert "Unexpected error: boom" == generation.error


# --- references ---------------------------------------------------------------
@pytest.mark.anyio
async def test_deleting_the_crawler_deletes_its_generations(
    write_repositories, member, create_crawler, generation_dispatcher
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    created = await _create(write_repositories, member, generation_dispatcher, draft.id)

    await crawler_service.delete_crawler(write_repositories, member, crawler.id)

    assert None is await write_repositories.instruction_generations.get_by_id(
        created.id
    )


@pytest.mark.anyio
async def test_deleting_a_version_nulls_the_generations_references(
    write_repositories, member, create_crawler, generation_dispatcher
):
    crawler, draft = await _draft(write_repositories, create_crawler)
    await crawler_version_service.publish_draft(
        write_repositories, member, crawler.id, draft.id
    )
    second = await crawler_version_service.create_draft(
        write_repositories, member, crawler.id
    )
    created = await _create(
        write_repositories, member, generation_dispatcher, second.id
    )
    stored = await write_repositories.instruction_generations.get_by_id(created.id)
    await write_repositories.instruction_generations.save(
        replace(stored, result_version_id=second.id)
    )
    await write_repositories.commit()

    await crawler_version_service.delete_version(write_repositories, member, second.id)

    generation = await write_repositories.instruction_generations.get_by_id(created.id)
    assert None is generation.crawler_version_id
    assert None is generation.result_version_id
