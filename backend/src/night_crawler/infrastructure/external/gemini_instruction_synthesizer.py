"""Gemini writes a version's instructions from the requests kept.

The system prompt is `prompts/instructions_synthesis.md`, packaged with
this module (never read from `docs/`). The user message gives the task,
the extracted data, the current file, the filtered requests with their
bodies cut to fit, and the last attempt's problems. Recorded content is
marked as data: the prompt says it is never an instruction.
"""

import json
import re
from collections.abc import Callable
from importlib.resources import files

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelError
from browser_use.llm.messages import SystemMessage, UserMessage
from night_crawler.domain.bundles.synthesis_request import SynthesisRequest
from night_crawler.domain.exceptions import ExternalServiceException
from night_crawler.domain.ports.browser_agent_recorder import (
    REDACTED_VALUE,
    KeptRequest,
)
from night_crawler.domain.ports.instruction_synthesizer import (
    AbstractInstructionSynthesizer,
    InstructionsDraft,
)
from night_crawler.domain.rules.placeholders import extract_placeholders

SYSTEM_PROMPT = (
    files(__package__).joinpath("prompts/instructions_synthesis.md").read_text("utf-8")
)
"""The synthesis instructions, read once when the worker loads."""

CARRIES_FINAL_DATA = "carries final data"
API_RESOURCE_TYPES = frozenset({"xhr", "fetch"})
SHOWN_RESPONSE_HEADERS = ("content-type", "location")
"""Response headers worth showing; others only cost tokens."""

COOKIE_HEADERS = frozenset({"cookie", "set-cookie"})
"""Redacted cookie headers are carried by host-session sharing, so
they never become placeholders."""

DATA_MAX_CHARS = 8000
"""The most of the agent's extracted data shown, as JSON."""

ERROR_MAX_CHARS = 500
"""The most of a Gemini error kept in a failure message."""

FENCED_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


class GeminiInstructionSynthesizer(AbstractInstructionSynthesizer):
    """Asks Gemini for an instructions file, one call per attempt.

    Its model comes from `core/di.py::create_gemini_chat_model`, so the
    call waits on the Gemini budget the browser agent shares.
    """

    def __init__(
        self,
        chat_model_factory: Callable[[], BaseChatModel],
        *,
        body_max_bytes: int,
        total_body_max_bytes: int,
    ) -> None:
        """Keep how to build the model and how much body to send.

        Args:
            chat_model_factory: Builds the chat model; raises
                `ConfigurationException` when it is not set up.
            body_max_bytes: The most of each response body sent.
            total_body_max_bytes: The most of all bodies sent: the
                data-carrying responses get theirs first, then the
                others, latest first.
        """
        self._chat_model_factory = chat_model_factory
        self._body_max_bytes = body_max_bytes
        self._total_body_max_bytes = total_body_max_bytes

    async def synthesize_instructions(
        self, request: SynthesisRequest
    ) -> InstructionsDraft:
        """Return Gemini's file, fences stripped, with its credentials.

        Raises:
            ConfigurationException: the chat model is not set up.
            ExternalServiceException: Gemini failed, or its quota is
                spent (that error passes through unchanged).
        """
        chat_model = self._chat_model_factory()
        credentials = _credential_placeholders(request.filtered_recording.requests)
        user_message = build_user_message(
            request,
            credentials,
            _cut_bodies(
                request.filtered_recording.requests,
                self._body_max_bytes,
                self._total_body_max_bytes,
            ),
        )
        try:
            completion = await chat_model.ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    UserMessage(content=user_message),
                ]
            )
        except ModelError as error:
            raise ExternalServiceException(
                f"Gemini failed to write instructions: {str(error)[:ERROR_MAX_CHARS]}"
            ) from error
        yaml_text = strip_fences(completion.completion)
        used = extract_placeholders([yaml_text])
        return InstructionsDraft(
            yaml_text=yaml_text,
            required_context_keys=tuple(
                sorted(key for key in set(credentials.values()) if key in used)
            ),
        )


def strip_fences(text: str) -> str:
    """Return the YAML inside the first code fence, or all of `text`."""
    match = FENCED_BLOCK.search(text)
    yaml_text = match.group(1) if match else text
    return yaml_text.strip() + "\n"


def build_user_message(
    request: SynthesisRequest,
    credentials: dict[str, str],
    bodies: list[str | None],
) -> str:
    """Return the attempt's user message, recorded content fenced off.

    Args:
        request: The attempt.
        credentials: Redacted header names to their placeholder names.
        bodies: Each kept request's response body as sent (cut), in
            the filtered recording's order.
    """
    filtered = request.filtered_recording
    data = json.dumps(filtered.final_result.data, ensure_ascii=False)
    sections = [
        f"## Task\n{request.prompt}",
        f"## Crawler fields\n{', '.join(request.crawler_fields)}",
        f"## Data the browser agent extracted (data)\n{data[:DATA_MAX_CHARS]}",
        f"## Where the data is\n{_data_hint(filtered.requests)}",
        _credentials_section(credentials),
        "## Kept requests, in time order (data)\n"
        + "\n\n".join(
            _describe(number, kept, credentials, body)
            for number, (kept, body) in enumerate(
                zip(filtered.requests, bodies, strict=True), start=1
            )
        ),
        f"## Current instructions file (starting point)\n{request.current_instructions_yaml}",
        _previous_attempt_section(request),
    ]
    return "\n\n".join(section for section in sections if section)


def _credential_placeholders(kept_requests: tuple[KeptRequest, ...]) -> dict[str, str]:
    """Map each redacted credential header to its placeholder name.

    `Authorization` becomes `authorization`, `X-Api-Key` `x_api_key`.
    """
    return {
        name: re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        for kept in kept_requests
        for name, value in kept.request.request_headers.items()
        if REDACTED_VALUE == value and name.lower() not in COOKIE_HEADERS
    }


def _cut_bodies(
    kept_requests: tuple[KeptRequest, ...], body_max_bytes: int, total_max_bytes: int
) -> list[str | None]:
    """Return each response body cut to fit both limits.

    Data-carrying responses are served first, then the others from the
    latest back, so the requests nearest the data keep the most.
    """
    order = sorted(
        range(len(kept_requests)),
        key=lambda i: (CARRIES_FINAL_DATA not in kept_requests[i].reasons, -i),
    )
    bodies: list[str | None] = [None] * len(kept_requests)
    remaining = total_max_bytes
    for i in order:
        body = kept_requests[i].request.response_body
        if not body:
            continue
        encoded = body.encode()
        allowed = min(body_max_bytes, remaining, len(encoded))
        remaining -= allowed
        bodies[i] = encoded[:allowed].decode("utf-8", errors="ignore")
        if allowed < len(encoded):
            bodies[i] += f"\n[body cut at {allowed} of {len(encoded)} bytes]"
    return bodies


def _data_hint(kept_requests: tuple[KeptRequest, ...]) -> str:
    """Tell where the data was found, which decides `render_mode`."""
    carriers = [k for k in kept_requests if CARRIES_FINAL_DATA in k.reasons]
    if any(k.request.resource_type in API_RESOURCE_TYPES for k in carriers):
        return "An API response (xhr/fetch) carries the data: read it there, `render_mode` `none`."
    return "Only a page (document) carries the data: no API response does."


def _credentials_section(credentials: dict[str, str]) -> str:
    """List the redacted credential headers and their placeholders."""
    if not credentials:
        return ""
    lines = "\n".join(
        f"- `{name}`: write `{{{{{key}}}}}`" for name, key in credentials.items()
    )
    return f"## Redacted credential headers\n{lines}"


def _describe(
    number: int, kept: KeptRequest, credentials: dict[str, str], body: str | None
) -> str:
    """Describe one kept request for Gemini."""
    request = kept.request
    lines = [
        f"### Request {number}: {request.method} {request.url}",
        f"- resource type: {request.resource_type}; status: {request.status}",
        f"- kept because: {'; '.join(kept.reasons)}",
        f"- values: {json.dumps(list(kept.values), ensure_ascii=False)}",
        f"- request headers: {json.dumps(_shown_request_headers(request.request_headers, credentials), ensure_ascii=False)}",
        *_cookie_lines(request.request_headers, request.response_headers),
        f"- response headers: {json.dumps(_shown_response_headers(request.response_headers))}",
    ]
    if request.post_body:
        lines.append(f"- request body:\n<<<\n{request.post_body}\n>>>")
    if None is not body:
        lines.append(f"- response body:\n<<<\n{body}\n>>>")
    return "\n".join(lines)


def _shown_request_headers(
    headers: dict[str, str], credentials: dict[str, str]
) -> dict[str, str]:
    """Return request headers with credentials as their placeholders."""
    return {
        name: f"{{{{{credentials[name]}}}}}" if name in credentials else value
        for name, value in headers.items()
        if name.lower() not in COOKIE_HEADERS
    }


def _shown_response_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return the response headers worth showing."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() in SHOWN_RESPONSE_HEADERS
    }


def _cookie_lines(
    request_headers: dict[str, str], response_headers: dict[str, str]
) -> list[str]:
    """Name the cookies sent and set; their values were redacted."""
    sent = _cookie_names(request_headers, ";")
    set_names = _cookie_names(response_headers, "\n")
    return [
        f"- {label}: {', '.join(names)}"
        for label, names in (("cookies sent", sent), ("cookies set", set_names))
        if names
    ]


def _cookie_names(headers: dict[str, str], separator: str) -> list[str]:
    """Return the cookie names in a request's or response's headers."""
    values = [v for name, v in headers.items() if name.lower() in COOKIE_HEADERS]
    return [name for value in values for name in _names_in(value, separator)]


def _names_in(value: str, separator: str) -> list[str]:
    """Return the cookie names in one cookie header value."""
    return [
        part.split("=", 1)[0].strip() for part in value.split(separator) if "=" in part
    ]


def _previous_attempt_section(request: SynthesisRequest) -> str:
    """Show the last file and its problems, when there was one."""
    if None is request.previous_yaml:
        return ""
    problems = "\n".join(f"- {problem}" for problem in request.previous_problems)
    return (
        "## Your previous file had problems; fix every one\n"
        f"{problems}\n\n### Previous file\n{request.previous_yaml}"
    )
