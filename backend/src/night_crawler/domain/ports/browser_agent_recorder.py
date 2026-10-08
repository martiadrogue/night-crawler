"""The port for a browser agent whose work on a site is recorded.

The agent browses to get what a generation's prompt asks for; the
recording of how it did so is what instructions are later written
from (`instruction_synthesizer.py`).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from night_crawler.domain.model.value_objects import InstructionRequest

REDACTED_VALUE = "<redacted>"
"""What a secret header value reads in a recording; cookie headers
keep their cookie names (`sid=<redacted>`)."""


@dataclass(frozen=True)
class AgentStep:
    """One action the agent took, in the order it took it.

    Attributes:
        index: Position in the recording, from 0; requests point at it.
        action: What it did (`navigate`, `click`, `input`, `scroll`,
            `extract`, `done`, …); `None` when the model gave none.
        params: The action's arguments as JSON-safe values (the URL
            navigated to, the text typed, …).
        target_xpath: The XPath of the element acted on, when the
            agent exposes one.
        url: The page's URL after the step.
        is_success: Whether the action ran without error.
        error: Why it failed, when it did.
    """

    index: int
    action: str | None
    url: str | None
    is_success: bool
    params: dict[str, Any] = field(default_factory=dict)
    target_xpath: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentRequest:
    """One request the agent's browser made.

    Attributes:
        step_index: The step during which it was made.
        url: The request URL; each redirect hop is its own request.
        method: HTTP method.
        resource_type: The browser's type, lower-cased (`document`,
            `xhr`, `fetch`, `script`, `image`, …).
        request_headers: Headers sent; secrets read `<redacted>`.
        post_body: The request body, if any.
        status: The response status; `None` when it failed.
        response_headers: Headers received; secrets read `<redacted>`.
        response_body: The body as text, kept for `document`, `xhr`,
            and `fetch` only, and cut at a set size.
        is_response_body_truncated: Whether the body was cut or
            dropped.
        failure: The network error, or `aborted`, when it failed.
    """

    step_index: int
    url: str
    method: str
    resource_type: str | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    post_body: str | None = None
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    is_response_body_truncated: bool = False
    failure: str | None = None


@dataclass(frozen=True)
class AgentFinalResult:
    """What the agent extracted, as it reported it.

    Attributes:
        data: JSON-safe values: the parsed JSON it answered with, or
            its text when that is not JSON; `None` without an answer.
        is_success: Whether the agent said it got what was asked.
    """

    data: Any
    is_success: bool


@dataclass(frozen=True)
class AgentRecording:
    """Everything the agent did and its browser sent, in order.

    Attributes:
        steps: The agent's actions.
        requests: Its browser's requests, oldest first.
        final_result: What it extracted.
        is_truncated: Whether bodies or requests were dropped to keep
            the recording under its stored size cap.
    """

    steps: tuple[AgentStep, ...]
    requests: tuple[AgentRequest, ...]
    final_result: AgentFinalResult
    is_truncated: bool = False


@dataclass(frozen=True)
class KeptRequest:
    """One request the filter kept, and why.

    Attributes:
        request: The recorded request.
        reasons: Why it was kept: `carries final data`, `feeds <url>`,
            `sets cookie <name>`, or `loads the page for <url>`.
        values: The values behind those reasons: final data it carries,
            values a later request uses, cookie names it sets.
    """

    request: AgentRequest
    reasons: tuple[str, ...]
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilteredRecording:
    """The requests that led to the agent's data, in time order.

    Attributes:
        requests: The chain, from its page navigation to the data;
            empty when no response carries the final data.
        final_result: The agent's extracted data, unchanged.
    """

    requests: tuple[KeptRequest, ...]
    final_result: AgentFinalResult


@dataclass(frozen=True)
class FilteredRequestSummary:
    """A kept request as stored on its generation, for debugging.

    Attributes:
        url: The request URL, cut to a stored size.
        method: HTTP method.
        status: The response status.
        reasons: Why it was kept.
    """

    url: str
    method: str
    status: int | None
    reasons: tuple[str, ...]


class AbstractBrowserAgentRecorder(ABC):
    """Runs a browser agent on a request and records what it does."""

    @abstractmethod
    async def record(self, request: InstructionRequest) -> AgentRecording:
        """Let the agent get the data the request asks for; record it.

        The request's current instructions are only a hint to the
        agent. A run that ends without the data is still returned, with
        `final_result.is_success` false.

        Raises:
            ConfigurationException: the agent is not set up (e.g. no
                API key).
            BrowserAgentException: the agent, its model, or its
                browser failed, or it ran out of time; carries what was
                recorded until then.
        """
