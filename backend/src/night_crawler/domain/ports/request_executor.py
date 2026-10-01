"""The port for sending one rendered request and harvesting it."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from night_crawler.domain.model.entities import MessageAidProxy, MessageSelector
from night_crawler.domain.model.value_objects import (
    Harvest,
    RenderedRequest,
    SessionState,
)


@dataclass(frozen=True)
class DispatchRequest:
    """Everything one engine needs for one template run.

    Attributes:
        rendered: The request, placeholders substituted.
        selectors: The template's flat selector list.
        session: Cookies and headers shared by earlier requests to the
            same host, or `None` when sharing is off.
        timeout_seconds: Per-request timeout.
        proxy: The proxy to go through, or `None` to connect directly.
        success_codes: The statuses that count as success, or `None`
            for any status below 400.
        is_host_session_sharing_enabled: Whether browser state may be
            reused for requests to the same exact host.
    """

    rendered: RenderedRequest
    selectors: list[MessageSelector]
    session: SessionState | None
    timeout_seconds: float
    proxy: MessageAidProxy | None = None
    success_codes: tuple[str, ...] | None = None
    is_host_session_sharing_enabled: bool = True


@dataclass(frozen=True)
class DispatchResult:
    """One request's harvest and the session it leaves behind.

    Attributes:
        harvest: The rows the selector tree read.
        status_code: Response status, when there was a response.
        session: Cookies the responses set (or the browser holds) and
            the shareable headers actually sent.
    """

    harvest: Harvest
    status_code: int | None
    session: SessionState


class AbstractRequestExecutor(ABC):
    """Sends a rendered request and applies its selectors.

    One implementation per render mode: `none` (httpx), `playwright`,
    and `stealth` (Patchright). The harvest rules are the same for all:
    an `iterator` repeats its children once per match, scoped to that
    match. A `click` (or `select`) acts on each match in turn and runs
    its children against the whole page after each action; httpx can't
    act, and runs them once against the page as fetched. Each
    iterator or click match is one row.
    """

    @abstractmethod
    async def execute(self, request: DispatchRequest) -> DispatchResult:
        """Send one request, harvest it, and capture its session.

        Raises:
            RequestFailedException: the request failed or timed out, or
                the response status isn't a success (`success_codes`,
                else 400 or above); its `failure_code` is the status,
                `"timeout"`, or `None`.
            ExternalServiceException: the response could not be read.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release resources pooled across one run."""
