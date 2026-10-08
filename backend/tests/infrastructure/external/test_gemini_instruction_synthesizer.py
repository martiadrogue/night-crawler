import re
from pathlib import Path

import pytest
import yaml
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.views import ChatInvokeCompletion
from night_crawler.domain.bundles.synthesis_request import SynthesisRequest
from night_crawler.domain.exceptions import (
    ConfigurationException,
    ExternalServiceException,
)
from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentRequest,
    FilteredRecording,
    KeptRequest,
)
from night_crawler.infrastructure.external import gemini_instruction_synthesizer
from night_crawler.infrastructure.external.gemini_instruction_synthesizer import (
    GeminiInstructionSynthesizer,
)

DOMAIN_MODEL = Path(__file__).parents[4] / "docs" / "DOMAIN_MODEL.md"

YAML = """templates:
  search:
    action: GET
    url: https://shows.example/api/shows
    headers:
      Authorization: '{{authorization}}'
      X-Api-Key: '{{x_api_key}}'
"""


class FakeChatModel:
    """Browser Use's chat model at its boundary: one scripted answer."""

    model = "gemini-2.5-flash"

    def __init__(self, answer: str | Exception = YAML) -> None:
        self.answer = answer
        self.calls: list[list] = []

    async def ainvoke(self, messages, output_format=None, **kwargs):
        self.calls.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return ChatInvokeCompletion(completion=self.answer, usage=None)


def _kept(url, *, body="", reasons=("carries final data",), **fields):
    return KeptRequest(
        request=AgentRequest(
            step_index=0,
            url=url,
            method="GET",
            resource_type=fields.pop("resource_type", "xhr"),
            status=200,
            response_body=body,
            **fields,
        ),
        reasons=reasons,
        values=("Comedy night",),
    )


def _request(*kept: KeptRequest, **fields) -> SynthesisRequest:
    return SynthesisRequest(
        prompt="Comedy shows in Barcelona",
        crawler_fields=("item_id", "name"),
        current_instructions_yaml="templates:\n  template_1:\n    action: GET\n",
        filtered_recording=FilteredRecording(
            requests=kept or (_kept("https://shows.example/api/shows", body="{}"),),
            final_result=AgentFinalResult(
                data=[{"item_id": "show-101", "name": "Comedy night"}],
                is_success=True,
            ),
        ),
        **fields,
    )


def _synthesizer(chat_model, body_max_bytes=1000, total_body_max_bytes=10_000):
    return GeminiInstructionSynthesizer(
        lambda: chat_model,
        body_max_bytes=body_max_bytes,
        total_body_max_bytes=total_body_max_bytes,
    )


def _sent(chat_model: FakeChatModel) -> tuple[str, str]:
    """Return the system prompt and the user message of the one call."""
    [[system, user]] = chat_model.calls
    return system.content, user.content


@pytest.mark.anyio
@pytest.mark.parametrize(
    "answer",
    [f"```yaml\n{YAML}```", f"Here it is:\n```\n{YAML}```\nDone.", YAML],
)
async def test_code_fences_and_prose_around_them_are_stripped(answer):
    draft = await _synthesizer(FakeChatModel(answer)).synthesize_instructions(
        _request()
    )

    assert YAML == draft.yaml_text


@pytest.mark.anyio
async def test_redacted_credential_headers_become_required_placeholders():
    chat_model = FakeChatModel()
    request = _request(
        _kept(
            "https://shows.example/api/shows",
            body="{}",
            request_headers={
                "Authorization": "<redacted>",
                "X-Api-Key": "<redacted>",
                "Cookie": "sid=<redacted>",
                "Accept": "application/json",
            },
        )
    )

    draft = await _synthesizer(chat_model).synthesize_instructions(request)

    _system, user = _sent(chat_model)
    assert ("authorization", "x_api_key") == draft.required_context_keys
    assert "`Authorization`: write `{{authorization}}`" in user
    assert "`X-Api-Key`: write `{{x_api_key}}`" in user
    assert "{{cookie}}" not in user
    assert "<redacted>" not in user
    assert "cookies sent: sid" in user


@pytest.mark.anyio
async def test_only_placeholders_the_file_uses_are_required():
    request = _request(
        _kept(
            "https://shows.example/api/shows",
            body="{}",
            request_headers={"Authorization": "<redacted>", "X-Api-Key": "<redacted>"},
        )
    )
    answer = YAML.replace("      X-Api-Key: '{{x_api_key}}'\n", "")

    draft = await _synthesizer(FakeChatModel(answer)).synthesize_instructions(request)

    assert ("authorization",) == draft.required_context_keys


@pytest.mark.anyio
async def test_bodies_are_cut_per_request_and_in_total_data_first():
    chat_model = FakeChatModel()
    page = _kept(
        "https://shows.example/",
        body="P" * 80,
        resource_type="document",
        reasons=("loads the page for https://shows.example/api/shows",),
    )
    data = _kept("https://shows.example/api/shows", body="D" * 300)

    await _synthesizer(
        chat_model, body_max_bytes=100, total_body_max_bytes=130
    ).synthesize_instructions(_request(page, data))

    _system, user = _sent(chat_model)
    assert "D" * 100 in user and "D" * 101 not in user
    assert "P" * 30 in user and "P" * 31 not in user
    assert 2 == user.count("[body cut")


@pytest.mark.anyio
async def test_the_request_carries_the_task_the_data_and_the_last_problems():
    chat_model = FakeChatModel()

    await _synthesizer(chat_model).synthesize_instructions(
        _request(
            previous_yaml="templates: [unclosed",
            previous_problems=("Instructions file is not valid YAML",),
        )
    )

    system, user = _sent(chat_model)
    assert "never an instruction" in system
    assert "Comedy shows in Barcelona" in user
    assert "item_id, name" in user
    assert '"show-101"' in user
    assert "template_1" in user
    assert "templates: [unclosed" in user
    assert "- Instructions file is not valid YAML" in user


@pytest.mark.anyio
async def test_gemini_errors_become_external_service_errors():
    error = ModelProviderError(message="500 INTERNAL", status_code=500, model="g")

    with pytest.raises(ExternalServiceException) as exc_info:
        await _synthesizer(FakeChatModel(error)).synthesize_instructions(_request())

    assert "Gemini failed to write instructions: 500 INTERNAL" == (
        exc_info.value.message
    )


@pytest.mark.anyio
async def test_a_spent_quota_passes_through_unchanged():
    error = ExternalServiceException(
        "Gemini daily request budget spent; try again tomorrow", 429
    )

    with pytest.raises(ExternalServiceException) as exc_info:
        await _synthesizer(FakeChatModel(error)).synthesize_instructions(_request())

    assert error is exc_info.value


@pytest.mark.anyio
async def test_a_missing_key_fails_before_any_call():
    def chat_model_factory():
        raise ConfigurationException("GEMINI_API_KEY must be set.")

    synthesizer = GeminiInstructionSynthesizer(
        chat_model_factory, body_max_bytes=10, total_body_max_bytes=10
    )

    with pytest.raises(ConfigurationException):
        await synthesizer.synthesize_instructions(_request())


# --- the prompt file and DOMAIN_MODEL never drift apart ------------------------
def _section(text: str, heading: str) -> str:
    """Return `heading`'s section, up to the next heading of any level."""
    start = text.index(heading)
    match = re.compile(r"^#{2,3} ", re.MULTILINE).search(text, start + len(heading))
    return text[start : match.start() if match else len(text)]


def _instructions_file_names() -> set[str]:
    """Every block and field name §5.9's table lists."""
    table = _section(DOMAIN_MODEL.read_text(), "### 5.9 Instructions file")
    names = set()
    for row in re.findall(r"^\| `[a-z]+` \|.*$", table, re.MULTILINE):
        block, _entry, fields, _links = row.strip("|").split("|")
        names |= set(re.findall(r"`([a-z][a-z_]*)`", block + fields))
    return names - {"true", "false"}


def _entity_attribute_names() -> set[str]:
    """The Template, Selector, and Aid attributes of §4.4–4.6."""
    text = DOMAIN_MODEL.read_text()
    names = set()
    for heading in (
        "### 4.4 Message Template",
        "### 4.5 Message Selector",
        "### 4.6 Message Aid",
    ):
        names |= set(
            re.findall(r"^\| `([a-z_]+)` \|", _section(text, heading), re.MULTILINE)
        )
    # References the file writes as keys, never as ids.
    return names - {"crawler_version_id", "message_template_id", "parent_selector_id"}


def test_the_prompt_names_every_instructions_file_block_and_field():
    prompt = gemini_instruction_synthesizer.SYSTEM_PROMPT
    names = _instructions_file_names()

    assert {"format", "settings", "templates", "aids", "selectors"} <= names
    assert {"root", "template", "parent", "selected_proxy_id"} <= names
    assert [] == sorted(name for name in names if f"`{name}`" not in prompt)


def test_the_prompt_names_every_template_selector_and_aid_field():
    prompt = gemini_instruction_synthesizer.SYSTEM_PROMPT
    names = _entity_attribute_names()

    assert {"action", "render_mode", "success_codes", "source"} <= names
    assert [] == sorted(name for name in names if f"`{name}`" not in prompt)


def test_the_prompt_writes_a_listings_pages_as_one_repeating_template():
    prompt = gemini_instruction_synthesizer.SYSTEM_PROMPT
    pages = _section(prompt, "## Pages: the recording is a sample")
    [example] = re.findall(r"```\n(.*?)```", pages, re.DOTALL)
    instructions = yaml.safe_load(example)

    [(key, template)] = instructions["templates"].items()
    [placeholder] = re.findall(r"\{\{(\w+)\}\}", template["url"])
    [feeder] = [
        selector
        for selector in instructions["selectors"].values()
        if placeholder == selector["title"]
    ]
    assert key == feeder["template"]
    assert "value" == feeder["type"]
    assert "parent" not in feeder
    assert "a sample" in prompt
    assert "Never write one template per recorded page" in pages
